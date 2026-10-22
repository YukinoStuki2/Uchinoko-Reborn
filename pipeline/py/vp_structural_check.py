# -*- coding: utf-8 -*-
"""dev#6 構造チェック(自己参照しない視覚検査の次善策)の判定ロジック。

設計文書: .devonly\\docs\\rd\\visual_check_rescope_20260802.md 4節。

背景: 従来の `_render_atlas_visual_check`(convert_noue.py)は
「アトラス化前プレビュー」と「アトラス化後レンダ」を比較するが、両者は
共通してretarget段(step02_retarget.py)の出力を祖先に持つため、retarget
自体が起こす破損(関節位置の誤り・90度回転ミス等)を検出できない
(自己参照)。この穴を埋めるため、**今回の実行結果に依存しない基準**
2種類で判定する:

  1. 向き不変性チェック: retarget後の各共通ボーンの回転(matrix_local)を、
     `refskel_{gender}.json`(Palworld本体から一度だけ抽出した、特定の
     アバター変換にも今回のretarget実行にも依存しない固定データ)から
     その場で再構築した基準骨格の回転と比較する。
  2. チェーン単調性/左右対称性チェック: retarget**前**(step01_clean.blend、
     アバター自身。retarget実行が何をしたかの情報を含まない)と
     retarget**後**(step02_{gender}.blend)で、親子ボーンの方向ベクトルの
     向きが反転していないか(内積の符号)。あわせて左右対応ボーン(_l/_r)の
     長さ比・鏡映角度も比較する(左右対称性は本来retargetで保たれるはず)。

このモジュールは判定ロジックのみを持ち、bpy/mathutilsに依存しない
(pure Python + 標準ライブラリのみ)。生データの抽出は
`pipeline\\py\\dump_retarget_structure.py`(Blender headless)が行う。
これにより判定ロジック自体はBlenderを起動せず単体テストできる。

閾値の根拠: work\\night_20260802b\\wp_6_progress.md に実測分布と
決定理由を記録している(relgate恒常3検体 x 2性別 = 6サンプルの正常値分布と、
意図的破損検体の異常値を比較して分離帯から選定。値を実測値そのままに
しない — CLAUDE.md「値を寄せて合わせる修正は却下」)。
"""
import math

# ---- 閾値(dev#6実測、根拠は work\night_20260802b\wp_6_progress.md) ----
# 向き不変性: relgate恒常3検体x2性別=6サンプルの実測worst caseは
# 0.0342〜0.0435deg(浮動小数点・座標変換の丸め程度、ほぼゼロ)。
# 意図的破損検体(headボーンのrollのみを75deg回す負の対照)は74.9999...degの
# 差が出た。両者の間に3桁の分離帯があるため、健全分布の最大値(0.0435deg)から
# 一桁以上離れた保守的な位置として 5.0deg を採用した(「値を寄せて合わせる」
# ではなく、実測ノイズの上限から意図的に大きく離した安全マージン)。
# 実測根拠: work\night_20260802b\wp_6_progress.md 「実測結果」節。
ORIENTATION_MAX_DEG = 5.0

# 左右対称性(鏡映角度): relgate 6サンプルの実測worst caseは0.0000〜0.3140deg。
# 意図的破損検体(hand_lのみ平行移動、反転しない程度)は37.2degのずれが出た。
# 健全分布の最大値(0.314deg)から一桁以上離した 15.0deg を採用。
# (dev#6b 2026-08-03: 鏡映角度は絶対判定のまま維持。dist_smoke偽陽性の実測
# (clavicle mirror_angle=0.00deg)が示すとおり、この基準自体は偽陽性を
# 出しておらず、オーナー裁定(案2)も長さ比のみを相対判定へ作り替える
# 対象としたため)。
SYMMETRY_MAX_DEG = 15.0

# 左右対称性(チェーン長さ比、長い方/短い方)—— dev#6b(2026-08-03)で
# 絶対判定から相対判定へ作り替えた。
#
# 経緯: PR #947 の絶対閾値(旧SYMMETRY_MAX_LENGTH_RATIO=1.15、relgate
# 恒常3検体×2性別=6サンプルの実測1.0000〜1.0071から導出)が、
# 2026-08-03朝の仮リリース関所(dist_smoke)で偽陽性を出した
# (dev#6コメント参照): dist_smoke検体(.devonly\fixtures\relgate\shapell\
# shapell.fbx、旧既定検体)は clavicle_l/clavicle_r の長さが実測23%
# 違う(=左右非対称なアバター)だけで、retarget自体は壊れていなかった。
# 「左右のボーン長が対称である」はユーザーアバターの不変条件ではない
# (片側だけの改変・装飾は普通にある)ため、絶対値でのFAIL判定は
# 原理的に誤検知を生む。
#
# オーナー裁定(2026-08-03朝、dev#6コメント、案2採用): 「対称であること」
# ではなく「対称性がretarget前後で変化していないこと」を見る。
# retarget前(step01_clean.blend、アバター自身、今回のretarget実行の
# 産物ではない)の左右長さ比と、retarget後(step02_{gender}.blend)の
# 同じ比を比べ、その変化率(after/before)だけを判定に使う。
#
# 実測(本WPで実施、work\wp_6b_relative_symmetry\work\wp_6b_relative_symmetry\
# probe\probe_results.json): shapell(Female、非対称検体、clavicle_l/upperarm_l
# のratio_before=1.232261 -> ratio_after=1.232260、change=0.999999)、
# prefab_flatapron(Male/Female、対称検体、全ペアchange=0.999999〜1.000001)。
# retarget(chibi_fit_armature)は関節位置をground-snap補正込みで移動する
# だけで、ボーン長そのものの左右比はスケール不変量として実質保存される
# ため、健全な変化率は非対称・対称いずれの入力でも1に対し1e-6オーダーの
# ノイズしか無い。負の対照(tests\shipcheck\dev6_structural_fixtures.py
# broken_symmetry: retarget前は対称(ratio_before=1.0)なhand_lをretarget後に
# Y方向へずらす)では変化率が1.414まで跳ね上がる。
#
# 健全ノイズ(実測最大1.000004程度)から4桁以上離れた保守的な位置として、
# 旧絶対閾値と同じ数値 1.15(15%)を「変化率」の閾値として採用した
# (値そのものの再利用であり、意味は絶対値→相対値へ変わっている。
# 「値を寄せて合わせる」に該当しない——閾値の意味が変わった上で、
# 新しい実測ノイズに対しても十分すぎるマージンがあることを確認済み)。
SYMMETRY_MAX_LENGTH_RATIO_CHANGE = 1.15

# dev#1232: 腕/指チェーン(auto_fit_pose()が強制的にパル標準方向へ回転させる
# 対象)は chain_reversals() のpre/post比較から除外する。
# step02_retarget.py の auto_fit_pose() は ROTATE_CHAINS 各ペアについて、
# 「アバター自身の現在の向き」を一切参照せず、常にパル標準骨格
# (refskel由来)自身のclavicle->upperarm等の方向へ強制的に回転させる
# (step02_retarget.py:156-180 `rot = cur_dir.rotation_difference(pal_dir)`)。
# つまりretarget後(step02)のこれらのチェーン方向は、入力アバターの
# 元の腕の向きに関係なく常にほぼ同じ(パル標準そのもの)になるよう
# 設計されている。一方retarget前(step01)の方向はアバター自身の
# レストポーズ(A-pose/T-pose/種族依存の肩形状等)に依存し、アバターごとに
# 大きく異なる。したがって「retarget前後でこの方向が保たれているか」を
# 比較するchain_reversals()の前提(pelvis直下の除外理由と同じ構造:
# 比較対象が意味を持たない)がROTATE_CHAINS全ペアで成り立たない。
#
# 実例(dev#1232、NJ2NMGFQ、All Species Fox類型): clavicle_l->upperarm_l の
# retarget前後dot=-0.008(ほぼ直交、90.46度)でFAILしたが、同じ実行の
# orientation_max_deg=0.0386度(パル標準骨格との向き差、独立基準)は
# 極小=健全そのものだった。これは「実際に壊れている」のではなく、
# この骨格のレストポーズにおける肩の向きがたまたまパル標準とほぼ
# 直交していた(auto_fit_poseが強制的にそこから標準向きへ回転させた)
# だけであり、閾値を負の値へ緩めても本質的な誤り(比較対象の選定)は
# 直らない(CLAUDE.md「値を寄せて合わせる修正は却下」)。
#
# ROTATE_CHAINS対象ボーンの向き健全性は orientation_diffs() が既に
# 独立に検証している(retarget後の実際の回転を、今回のアバター・
# retarget実行に依存しないrefskel由来の基準骨格と比較する——自己参照
# しない設計、dev#6本来の目的そのもの)。実際に腕が壊れた既知の破損
# パターン(negctrl1: 左右腕関節の丸ごと入れ替え)はorientation側で
# 177〜180度の差として検出される(dev6_structural_fixtures.py
# 冒頭docstring参照)ため、chain側での除外は検出力を落とさない。
ROTATE_CHAIN_PAIRS = {
    ("clavicle_l", "upperarm_l"), ("upperarm_l", "lowerarm_l"),
    ("lowerarm_l", "hand_l"), ("hand_l", "middle_01_l"),
    ("clavicle_r", "upperarm_r"), ("upperarm_r", "lowerarm_r"),
    ("lowerarm_r", "hand_r"), ("hand_r", "middle_01_r"),
}

# 欠損時の方針: step01(retarget前)データが無い/対応する左右ペアが特定できない
# 場合(例: 一部アバターでball_l/ball_rのような末端ボーンがhumanoidマップに
# 無い、実測: prefab_flatapronのfoot_l→ball_lで確認済み)は、相対判定が
# できないためこのペアの長さ比チェックをスキップする(このモジュール内の
# 他の欠損データ処理——_mirror_axisがNoneを返すケース等——と同じ方針)。
# 絶対値へフォールバックしない(フォールバックすると同じ偽陽性クラスが
# 部分的に復活するため)。


def _quat_angle_deg(q1, q2):
    """2つの単位クォータニオン[w,x,y,z]間の回転角(度、0-180)。
    Blenderの Quaternion.rotation_difference().angle と同じ定義
    (符号反転(q, -qは同じ回転)を吸収するため内積は絶対値を取る)。"""
    dot = sum(a * b for a, b in zip(q1, q2))
    dot = max(-1.0, min(1.0, abs(dot)))
    return math.degrees(2 * math.acos(dot))


def orientation_diffs(ref_quat, test_quat, common_bones):
    """{bone: 角度差(deg)}。両方に存在するボーンのみ。"""
    diffs = {}
    for name in common_bones:
        q1 = ref_quat.get(name)
        q2 = test_quat.get(name)
        if q1 is None or q2 is None:
            continue
        diffs[name] = _quat_angle_deg(q1, q2)
    return diffs


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _normalized(a):
    n = _norm(a)
    if n < 1e-9:
        return None
    return [a[0] / n, a[1] / n, a[2] / n]


def chain_vector(points, parent, child):
    p = points.get(parent)
    c = points.get(child)
    if p is None or c is None:
        return None
    return _sub(c, p)


def chain_reversals(step01_points, step02_points, chain_pairs):
    """親子ペアごとに retarget 前後の方向ベクトルの内積符号を見る。
    戻り値: [(parent, child, dot), ...](両方の点が揃ったペアのみ)。
    dot < 0 は90度以上の反転(このチェックのFAIL条件そのもの、閾値不要)。

    parent=="pelvis" のペアは対象外にする。理由(実測で判明、
    work\\night_20260802b\\wp_6_progress.md参照): step02_retarget.py の
    chibi_fit_armature() は pelvis を意図的に一切移動しない
    (docstring「pelvisは移動しない(グローバル配置で一致済み)」)。
    一方、pelvis以外のCHIBI_CANDIDATES対象ボーン(spine_01・thigh_l等)は
    ground-snap補正量dzを加えたアバター実位置へ移動される。この結果、
    pelvis(補正なし・retarget前後で不変)とその子(補正あり)を比較すると、
    retargetが正しく動作していてもdz分だけ方向が系統的にずれる
    (relgate恒常6サンプル全件で実測、pelvis→spine_01のdotは
    -0.85〜-0.98の範囲で毎回負になった。壊れているサンプルは1つも
    無いのに全件で「反転」判定になり、偽陽性の温床になることを確認した)。
    これはretargetの破損とは無関係な、chibi_fit_armatureの設計上の
    既知の非対称性であり、値を寄せて閾値を調整するのではなく、
    比較として意味を持たないペアを構造的に除外するのが正しい対処。
    pelvis以外を親に持つペア(spine_01→spine_02、thigh_l→calf_l等、
    どちらもground-snap補正込みの実位置同士の比較)は影響を受けない
    (実測: 0.9998〜1.0000で一貫して正)。

    dev#1232: ROTATE_CHAIN_PAIRS(腕/指チェーン)も同様の理由で除外する
    (このファイル冒頭、SYMMETRY_MAX_LENGTH_RATIO_CHANGE直上のコメント
    参照)。pelvisと違い「片方の端点だけが補正される」系統的オフセットが
    理由ではなく、auto_fit_pose()がチェーン全体を毎回パル標準方向へ
    強制的に回転させる(=retarget前の向きを参照しない)設計であるため、
    pre/post比較そのものが意味を持たない。"""
    results = []
    for parent, child in chain_pairs:
        if parent == "pelvis":
            continue
        if (parent, child) in ROTATE_CHAIN_PAIRS:
            continue
        v_before = chain_vector(step01_points, parent, child)
        v_after = chain_vector(step02_points, parent, child)
        if v_before is None or v_after is None:
            continue
        nb, na = _normalized(v_before), _normalized(v_after)
        if nb is None or na is None:
            continue
        results.append((parent, child, _dot(nb, na)))
    return results


def _mirror_axis(points):
    """clavicle_l/rのpelvis相対位置から、左右対称の鏡映軸(0=x,1=y,2=z)を
    検体非依存に決める(2軸のうち符号が反転し、かつ振れ幅が最大の軸)。
    ハードコードした「X軸が左右」のような決め打ちを避けるため、実際の
    骨格データから毎回導出する。

    dev#1609: この関数が返す軸は、あくまでpelvis->clavicleオフセットに
    基づく**参考情報**(ログ出力・後方互換用)であり、symmetry_diffs()の
    実際の判定にはもう使わない(_mirror_axis_for_vectors()を参照)。
    レストポーズによっては、この軸と実際に各チェーンが左右反転している
    軸が一致しないケースがある(JTBCNXCA実例: この関数はpelvis-clavicle
    オフセットからY軸を選んだが、腕チェーン(clavicle->upperarm)の実方向
    ベクトルはX軸で反転していた。Y軸を全チェーンへ一律適用すると
    mirror_angle=180度相当の誤検知になる)。"""
    pelvis = points.get("pelvis")
    cl = points.get("clavicle_l")
    cr = points.get("clavicle_r")
    if pelvis is None or cl is None or cr is None:
        return None
    dl = _sub(cl, pelvis)
    dr = _sub(cr, pelvis)
    return _mirror_axis_for_vectors(dl, dr)


def _mirror_axis_for_vectors(v_l, v_r):
    """左右2ベクトルv_l, v_rそのものから鏡映軸(0=x,1=y,2=z)を決める
    (2軸のうち符号が反転し、かつ振れ幅が最大の軸)。_mirror_axis()の
    コア判定ロジックを、任意の左右ベクトルペアに適用できるよう汎用化した
    もの(dev#1609)。符号が反転する軸が無ければNone(この入力からは
    鏡映軸を決定できない=比較不能。呼び出し側でスキップする)。"""
    best_axis, best_score = None, -1.0
    for axis in range(3):
        if v_l[axis] * v_r[axis] >= 0:
            continue  # 符号が同じ = この軸は鏡映軸ではない
        score = abs(v_l[axis]) + abs(v_r[axis])
        if score > best_score:
            best_score = score
            best_axis = axis
    return best_axis


def _lr_length_ratio(points, parent, child, parent_r, child_r):
    """左右チェーン区間の長さ比(長い方/短い方、常に>=1)。どちらかの点が
    欠けている・長さがほぼゼロなら None(比較不能。呼び出し側でスキップする
    ためのシグナル、0や1へフォールバックしない)。"""
    v_l = chain_vector(points, parent, child)
    v_r = chain_vector(points, parent_r, child_r)
    if v_l is None or v_r is None:
        return None
    len_l, len_r = _norm(v_l), _norm(v_r)
    if len_l < 1e-6 or len_r < 1e-6:
        return None
    return max(len_l, len_r) / min(len_l, len_r)


def symmetry_diffs(step01_points, step02_points, lr_pairs, chain_pairs):
    """左右対応するチェーン区間について、鏡映角度(retarget後のみ、絶対判定)と
    長さ比の変化率(retarget前後、相対判定——dev#6b)を比較する。

    dev#1609: 鏡映軸はチェーンペアごとに、そのペア自身の実方向ベクトル
    (v_l, v_r)から個別に判定する(_mirror_axis_for_vectors())。旧実装は
    骨格全体で単一のグローバル軸(pelvis->clavicleオフセットの符号のみ
    から決定、_mirror_axis())をすべてのチェーンへ一律適用していたが、
    レストポーズによっては「pelvis->clavicleのオフセット軸」と「実際に
    そのチェーンが左右反転している軸」が一致しない検体があり、その場合
    mirror_angle=180deg相当の誤検知でFATALになっていた(JTBCNXCA実例:
    pelvis-clavicleオフセットはY軸反転だったが、腕チェーンの実方向は
    X軸で反転していた)。ペアごとに軸を独立決定することでこの不一致を
    構造的に解消する。あるペアで鏡映軸が決定できない(符号が反転する軸が
    無い)場合はそのペアのみスキップする(他のペアの判定には影響しない)。

    戻り値: (results, mirror_axis)。mirror_axisは_mirror_axis()による
    参考情報(ログ出力・後方互換用)であり、この関数自体の判定には
    使わない——決定できなくても(None)ペアごとの判定は独立に続行する。

    各resultsエントリの length_ratio_before/length_ratio_change は、
    step01(retarget前)側の同じ左右ペアが特定できないときNoneになる
    (SYMMETRY_MAX_LENGTH_RATIO_CHANGE直上のコメント参照)。evaluate()側は
    Noneのときこのペアの長さ比チェックをスキップする(鏡映角度チェックは
    従来どおり独立して働く)。"""
    axis = _mirror_axis(step02_points)  # 参考情報(ログ用)。判定には不使用
    results = []
    lr_map = dict(lr_pairs)
    for parent, child in chain_pairs:
        if not (parent.endswith("_l") and child.endswith("_l")):
            continue
        parent_r = lr_map.get(parent)
        child_r = lr_map.get(child)
        if parent_r is None or child_r is None:
            continue
        v_l = chain_vector(step02_points, parent, child)
        v_r = chain_vector(step02_points, parent_r, child_r)
        if v_l is None or v_r is None:
            continue
        len_l, len_r = _norm(v_l), _norm(v_r)
        if len_l < 1e-6 or len_r < 1e-6:
            continue
        pair_axis = _mirror_axis_for_vectors(v_l, v_r)
        if pair_axis is None:
            continue  # このペア自身からは鏡映軸を決定できない(比較不能)
        mirrored_r = list(v_r)
        mirrored_r[pair_axis] = -mirrored_r[pair_axis]
        nl, nmr = _normalized(v_l), _normalized(mirrored_r)
        if nl is None or nmr is None:
            continue
        cosang = max(-1.0, min(1.0, _dot(nl, nmr)))
        angle = math.degrees(math.acos(cosang))
        ratio_after = max(len_l, len_r) / min(len_l, len_r)
        ratio_before = _lr_length_ratio(step01_points, parent, child, parent_r, child_r)
        ratio_change = (ratio_after / ratio_before) if ratio_before else None
        results.append({
            "parent": parent, "child": child,
            "parent_r": parent_r, "child_r": child_r,
            "mirror_axis": pair_axis,
            "mirror_angle_deg": angle,
            "length_ratio": ratio_after,
            "length_ratio_before": ratio_before,
            "length_ratio_change": ratio_change,
        })
    return results, axis


def evaluate(data):
    """dump_retarget_structure.pyが書き出したdictを判定する。

    data キー: common_bones, ref_quat, test_quat, chain_pairs, lr_pairs,
               step01_points, step02_points (すべて dump_retarget_structure.py
               のJSON出力そのまま)。

    戻り値: {"pass": bool, "orientation": {...}, "chain": {...}, "symmetry": {...}}
    """
    common_bones = data["common_bones"]
    ref_quat = data["ref_quat"]
    test_quat = data["test_quat"]
    chain_pairs = [tuple(p) for p in data["chain_pairs"]]
    lr_pairs = [tuple(p) for p in data["lr_pairs"]]
    step01_points = data["step01_points"]
    step02_points = data["step02_points"]

    o_diffs = orientation_diffs(ref_quat, test_quat, common_bones)
    o_max = max(o_diffs.values()) if o_diffs else 0.0
    o_worst = max(o_diffs, key=o_diffs.get) if o_diffs else None
    o_fail_bones = {n: d for n, d in o_diffs.items() if d > ORIENTATION_MAX_DEG}

    reversals = chain_reversals(step01_points, step02_points, chain_pairs)
    reversed_chains = [(p, c, d) for p, c, d in reversals if d < 0.0]

    sym, axis = symmetry_diffs(step01_points, step02_points, lr_pairs, chain_pairs)
    # dev#6b: 長さ比は「変化率」(length_ratio_change)で判定する。Noneは
    # step01側でこのペアの左右比較ができなかった(スキップ、フォールバック
    # しない——SYMMETRY_MAX_LENGTH_RATIO_CHANGE直上のコメント参照)。
    sym_fail = [s for s in sym
                if s["mirror_angle_deg"] > SYMMETRY_MAX_DEG
                or (s["length_ratio_change"] is not None
                    and s["length_ratio_change"] > SYMMETRY_MAX_LENGTH_RATIO_CHANGE)]

    ok = (not o_fail_bones) and (not reversed_chains) and (not sym_fail)
    return {
        "pass": ok,
        "orientation": {
            "n_bones": len(o_diffs), "max_deg": o_max, "worst_bone": o_worst,
            "fail_bones": o_fail_bones, "threshold_deg": ORIENTATION_MAX_DEG,
        },
        "chain": {
            "n_pairs": len(reversals),
            "reversed": [{"parent": p, "child": c, "dot": d}
                         for p, c, d in reversed_chains],
            "worst_dot": min((d for _, _, d in reversals), default=None),
        },
        "symmetry": {
            "mirror_axis": axis, "n_pairs": len(sym), "fail": sym_fail,
            "threshold_deg": SYMMETRY_MAX_DEG,
            "threshold_length_ratio_change": SYMMETRY_MAX_LENGTH_RATIO_CHANGE,
            "all": sym,
        },
    }
