# -*- coding: utf-8 -*-
"""dev#136: VRMパーサ/インポート経路へのファズ・プロパティベーステスト。

## 対象の特定(進捗ログ C:\\P\\Work\\DiveToPalworld\\work\\night_20260802\\136_progress.md
に詳細な調査記録あり)

VRM/glTFの**バイナリ解析そのもの**は `pipeline\\blender\\step01_import_vrm.py` が
`bpy` + VRMアドオン(io_scene_vrm)で行っており、完全にBlender依存。このリポジトリの
Blender非依存(純Python)コードには、VRM/glTFバイナリを直接パースする箇所が存在
しない(pipeline\\py\\ 全体を "glTF"/"VRMC_"/".glb"/chunk magic 等でgrepしても
ヒットなし)。

そこで、VRMのマテリアル構造(マテリアル名・テクスチャ・ベースカラー・
alpha_mode)を**直接解釈する最初のBlender非依存コード**である
`vp_atlas.plan_avatar(meta)` を対象に採用した。`meta` は
`avatar_meta.json`(step01_import_vrm.pyがVRMファイルから生成する中間データ)の
中身そのもので、実質的に「VRMの材質情報をパースした結果を読み解く」層である。
plan_avatarはbpy非依存・ファイルI/Oなしの純粋関数で、単体テストに適する。

## 方式

追加ライブラリ(hypothesis等)は導入しない(このWPの聖域)。標準ライブラリの
`random.Random(FIXED_SEED)` で合成 meta dict を生成する。同じシードなら常に
同じケース列になる(決定的)。

## 検証する性質

- P1(既にガード済みの形は例外を投げない): plan_avatarが自前で処理済みの
  境界(slotsキー欠落→既定{}、slots空、texture=null かつ base_color無し→
  skippedへ記録、非PNG拡張子→skippedへ記録)は、例外なく完了する。
- 負の対照: P1が本当に有効な検知力を持つことを示すため、plan_avatarの
  ソースを**メモリ上でのみ**1箇所改変した「壊れた版」を作り、P1が安全だと
  示した入力に対して壊れた版は例外を投げることを実測する
  (製品ファイルそのものは一切変更しない)。
- P2(壊れた入力は診断可能であるべき): 型の入れ替え・配列/辞書の入れ替え・
  必須キー欠落・巨大な数値・深いネスト・不正なコードポイント文字列などの
  構造的に壊れたmetaを渡したとき、plan_avatarは成功するか、こちらが
  定義した診断可能な例外(どのslotが不正かを含む)を投げるべきである。
  裸のKeyError/AttributeError/TypeError/IndexError/ValueErrorがそのまま
  呼び出し元へ届く経路は性質違反とみなす。

  **【2026-08-02 dev#740で修正済み】** 当初(本ファイル作成時点)は性質違反
  だった。plan_avatarに専用の例外型が一つも無く(`vp_atlas.py`に
  `class .*Error`定義なし)、構造的に壊れたmetaは複数の異なる裸の例外を
  送出していた。当時は「製品コードを変更しない」がこのWP(dev#136)の聖域
  だったため、代表的な壊れ方ごとに最小の再現ケースを個別に
  `xfail(strict=True)` として記録し、次の担当がそのまま直せる状態にして
  あった。dev#740でこの負債を解消: `vp_atlas.AvatarMetaError`
  (`ValueError`のサブクラス)を新設し、壊れたmetaは必ずこの型で
  (`.slot_id`/`.field`に文脈を保持し、元例外を`raise ... from e`で連鎖
  させて)送出するよう`plan_avatar`を直した。7件のxfailは全て正の対照
  (`pytest.raises(vp_atlas.AvatarMetaError)`)へ書き換え済み。ランダム
  ファズ側も「捕捉される例外は必ず`AvatarMetaError`であり、それ以外の
  裸の例外は一切出ない」ことをプロパティとして監視する形に更新した
  (旧KNOWN_BARE_EXCEPTION_TYPESは、直した後もなお同じ壊し方の集合を
  ファズが実際に踏んでいることの根拠としてのみ残す)。

  **【2026-08-02 dev#936で追随修正】** `KNOWN_BARE_EXCEPTION_TYPES`の
  4種類目(KeyError)を決め打ちしていたため、CI(.github\\workflows\\ci.yml
  がpython-version: "3.11"に固定)で`test_defect_base_color_dict_raises_avatar_meta_error`
  と`test_plan_avatar_fuzz_stays_within_known_defect_catalog`が確実に赤くなって
  いた。原因は`vp_atlas.solid_color_key()`内の`rgba[:4]`(base_colorがdictの
  ときにdictへスライスを当てる形)が投げる裸例外の型がCPythonのバージョンに
  依存すること: sliceオブジェクトがhashableになったPython 3.12(gh-100659)
  以降は辞書の`[:4]`アクセスがハッシュ照合まで進みKeyErrorになるが、3.11
  以前はsliceがunhashableなためTypeError(unhashable type: 'slice')になる。
  `plan_avatar`側の`except (TypeError, ValueError, KeyError)`は元々どちらの
  型も正しく捕捉してAvatarMetaErrorへ`raise ... from e`で連鎖させておりwrap
  ロジック自体は壊れていない(=製品コードの欠陥ではない)。決め打ちを止め、
  このインタプリタで実際に`dict[:4]`が投げる型を実測(`_dict_slice_bare_exception_type()`)
  して期待値に使うことで、Pythonバージョンが何であっても決定的に緑にした。

実行: python -m pytest pipeline/py/test_vp_atlas_fuzz.py -q
"""
import inspect
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_atlas  # noqa: E402

FIXED_SEED = 20260802  # dev#136着手日。固定シードで再現性を担保。


def _dict_slice_bare_exception_type():
    """`vp_atlas.solid_color_key()`内の`rgba[:4]`は、base_colorが辞書
    (例: {"r":1,"g":2,"b":3,"a":4})のとき「辞書へスライスを当てる」形になる。
    この操作が投げる裸例外の型はCPythonのバージョンに依存する: sliceオブジェクトが
    hashableになったPython 3.12(gh-100659)以降は辞書の`[:4]`アクセスがハッシュ
    照合まで進みKeyErrorになるが、3.11以前(このプロジェクトのCIが固定する
    バージョン、.github\\workflows\\ci.yml:59)ではsliceがunhashableなため
    TypeError(unhashable type: 'slice')になる。dev#936: この型をKeyErrorへ
    決め打っていたため、CI(Python 3.11)では対応する試験が確実に赤くなっていた
    (`plan_avatar`側の`except (TypeError, ValueError, KeyError)`は元々どちらの
    型も正しく捕捉してAvatarMetaErrorへ連鎖させており、wrapロジック自体は
    壊れていない=製品コードの欠陥ではない)。決め打たず、このインタプリタで
    実際に何が起きるかを都度実測して期待値として使う。"""
    try:
        {"r": 1, "g": 2, "b": 3, "a": 4}[:4]
    except Exception as e:  # noqa: BLE001 -- ここは型を観測するのが目的
        return type(e)
    raise AssertionError(
        "dict[:4] が例外を投げなかった"
        "(vp_atlas.solid_color_keyがrgba[:4]でdictを弾く前提が崩れている)")


# base_colorがdictのとき`solid_color_key`が実際に投げる裸例外の型(dev#936、
# このインタプリタでの実測値。CPythonバージョンにより KeyError/TypeError が
# 変わる。上のdocstring参照)。
DICT_SLICE_BARE_EXC_TYPE = _dict_slice_bare_exception_type()

# dev#740修正前、plan_avatarが裸で投げていた例外の型カタログ(歴史的参照)。
# 修正後はこれらの壊し方は全て vp_atlas.AvatarMetaError に統一されているはず
# なので、ファズ側はこの集合を「壊し方のカテゴリが今回も一通り踏まれたか」の
# 内訳確認にのみ使う(実際に送出される型は AvatarMetaError 固定を期待する)。
# 4種類目(元はKeyError決め打ち)は、上のDICT_SLICE_BARE_EXC_TYPE実測値に
# 置き換えてある(dev#936、CPythonバージョン依存の吸収)。
KNOWN_BARE_EXCEPTION_TYPES = (AttributeError, TypeError, ValueError, DICT_SLICE_BARE_EXC_TYPE)


# ============================================================== ヘルパー

def _valid_slot(orig_name="body", texture="t00.png", base_color=None,
                 alpha_mode="OPAQUE", double_sided=False):
    return {
        "orig_name": orig_name,
        "texture": texture,
        "base_color": base_color if base_color is not None else [0.5, 0.5, 0.5, 1.0],
        "alpha_mode": alpha_mode,
        "double_sided": double_sided,
    }


def _valid_meta(n_slots=3):
    """avatar_meta.json相当の、素性の良いmetaを作る(step01_import_vrm.pyが
    書き出す実際のスキーマに合わせる: L.819-822, L.881-884参照)。"""
    slots = {}
    for i in range(n_slots):
        slots[f"m{i:02d}"] = _valid_slot(
            orig_name=f"mat{i}", texture=f"t{i:02d}.png",
            base_color=[0.1 * i, 0.2 * i, 0.3 * i, 1.0])
    return {"slots": slots}


def _get_mutated_plan_avatar_missing_slots_default():
    """負の対照用: plan_avatarの実ソースを取得し、`meta.get("slots", {})`
    (slotsキー欠落を許容するデフォルト)だけを `meta["slots"]` に置き換えた
    「壊れた版」をメモリ上でexecして返す。**vp_atlas.pyファイル自体は
    一切変更しない**(execは独立した名前空間で行い、書き込みはしない)。"""
    src = inspect.getsource(vp_atlas.plan_avatar)
    needle = 'meta.get("slots", {})'
    assert needle in src, (
        "vp_atlas.plan_avatar()のソース形状が変わったため、この負の対照は"
        "更新が必要(dev#136 test_vp_atlas_fuzz.py)。"
    )
    mutated_src = src.replace(needle, 'meta["slots"]')
    # classify_material/plan_label/LABELS等の依存解決のため、実モジュールの
    # 名前空間をベースに使う(コピーなのでvp_atlas本体は無傷)。
    ns = dict(vars(vp_atlas))
    exec(compile(mutated_src, "<mutated_plan_avatar_dev136>", "exec"), ns)
    return ns["plan_avatar"]


# ==================================================== P1: 既知の安全な境界

def test_plan_avatar_survives_already_guarded_shapes():
    """plan_avatarが現に自前でガードしている境界は、例外を投げずに完了する。"""
    guarded_cases = {
        "slots_key_missing": {"other": 1},
        "slots_empty_dict": {"slots": {}},
        "texture_none_no_base_color": {"slots": {"m00": {"orig_name": "body"}}},
        "texture_non_png_extension": {
            "slots": {"m00": {"orig_name": "body", "texture": "t.jpg"}}},
        "texture_empty_string": {
            "slots": {"m00": {"orig_name": "body", "texture": ""}}},
    }
    for name, meta in guarded_cases.items():
        try:
            plan, skipped = vp_atlas.plan_avatar(meta)
        except Exception as e:  # noqa: BLE001 -- ここは「例外が出ないこと」自体を検証している
            pytest.fail(f"guarded case {name!r} raised {type(e).__name__}: {e}")
        assert isinstance(plan, dict) and "body" in plan and "parka" in plan


def test_plan_avatar_healthy_meta_never_raises_avatar_meta_error():
    """負の対照(dev#740): 健全なavatar_meta.json相当のmetaは、
    AvatarMetaError(または他の何らかの例外)を一切出さないこと。
    dev#740の修正は「壊れた入力の診断性を上げる」ことが目的であり、
    健全な入力を誤って不正判定する(過剰検査)regressionが無いことを
    別途確認する必要がある。"""
    meta = _valid_meta(n_slots=5)
    plan, skipped = vp_atlas.plan_avatar(meta)
    assert skipped == []
    assert isinstance(plan, dict) and "body" in plan and "parka" in plan

    # alpha_mode=0(falsy・非文字列)は、既存コードでも
    # `(alpha_mode or "").upper()` の短絡評価により元々クラッシュしない
    # 形だった。dev#740の修正がこの安全な形を過剰検査で新たに壊して
    # いないことを確認する(旧仕様との厳密な後方互換性)。
    meta_falsy_alpha_mode = {
        "slots": {"m00": {"orig_name": "body", "texture": "t00.png",
                           "alpha_mode": 0}}}
    plan2, skipped2 = vp_atlas.plan_avatar(meta_falsy_alpha_mode)
    assert skipped2 == []


def test_negative_control_slots_default_guard_is_load_bearing():
    """負の対照: 上のtest_plan_avatar_survives_already_guarded_shapesが
    無意味な(何を壊しても緑の)試験でないことを実測する。

    plan_avatarの `meta.get("slots", {})` を `meta["slots"]` に置き換えた
    壊れた版を作り、slotsキーが欠けたmetaに対して:
      - 本物(vp_atlas.plan_avatar)は例外を投げない(=上のP1試験が緑になる根拠)
      - 壊れた版はKeyErrorで落ちる(=このガードを取り除けば検知できる証拠)
    ことを両方確認する。"""
    meta_without_slots_key = {"other": 1}

    # 壊す前: 本物は例外なし
    plan, skipped = vp_atlas.plan_avatar(meta_without_slots_key)
    assert skipped == []

    # 壊した後: KeyErrorで落ちる
    broken_plan_avatar = _get_mutated_plan_avatar_missing_slots_default()
    with pytest.raises(KeyError):
        broken_plan_avatar(meta_without_slots_key)


# ======================================== P2: 既知の欠陥(dev#740で修正済み)
#
# それぞれ最小の単一再現入力。dev#136時点ではxfail(strict=True)として
# 記録するに留めていたが、dev#740で`vp_atlas.AvatarMetaError`を新設し
# plan_avatar()を直したため、いずれも「専用の診断例外が飛ぶこと」を
# 検証する正の対照へ書き換える。メッセージに壊れた箇所の識別子
# (slot_id/フィールド名)が含まれることも確認する。

def test_defect_meta_not_a_dict_raises_avatar_meta_error():
    """meta自体がdict以外(None/list/str/int)。
    修正前: meta.get(...)が素のAttributeErrorを投げていた(文脈無し)。
    再現: vp_atlas.plan_avatar(None)"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar(None)
    assert isinstance(exc_info.value.__cause__, AttributeError)
    assert "root" in str(exc_info.value) or exc_info.value.field == "<root>"
    assert "NoneType" in str(exc_info.value)


def test_defect_slots_not_a_dict_raises_avatar_meta_error():
    """meta['slots']がdict以外(list等)。
    修正前: sorted(slots.keys())が素のAttributeErrorを投げていた。
    再現: vp_atlas.plan_avatar({'slots': []})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar({"slots": []})
    assert isinstance(exc_info.value.__cause__, AttributeError)
    assert exc_info.value.field == "slots"
    assert "slots" in str(exc_info.value)


def test_defect_slot_info_not_a_dict_raises_avatar_meta_error():
    """slots[slot_id](=info)がdict以外(文字列等)。
    修正前: info.get('texture')が素のAttributeErrorを投げていた。
    再現: vp_atlas.plan_avatar({'slots': {'m00': 'not-a-dict'}})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar({"slots": {"m00": "not-a-dict"}})
    assert isinstance(exc_info.value.__cause__, AttributeError)
    assert exc_info.value.slot_id == "m00"
    assert "m00" in str(exc_info.value)


def test_defect_texture_not_a_string_raises_avatar_meta_error():
    """textureがstr以外(int等)。
    修正前: tex.lower()が素のAttributeErrorを投げていた。
    再現: vp_atlas.plan_avatar({'slots': {'m00': {'orig_name': 'body',
    'texture': 123}}})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar(
            {"slots": {"m00": {"orig_name": "body", "texture": 123}}})
    assert isinstance(exc_info.value.__cause__, AttributeError)
    assert exc_info.value.slot_id == "m00"
    assert exc_info.value.field == "texture"
    assert "m00" in str(exc_info.value) and "texture" in str(exc_info.value)


def test_defect_base_color_non_numeric_raises_avatar_meta_error():
    """base_colorが数値でない要素を含む。
    修正前: solid_color_key() 内の float(x) が素のValueErrorを投げていた。
    再現: vp_atlas.plan_avatar({'slots': {'m00': {'orig_name': 'body',
    'texture': None, 'base_color': ['a', 'b', 'c', 'd']}}})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar({
            "slots": {"m00": {"orig_name": "body", "texture": None,
                               "base_color": ["a", "b", "c", "d"]}}})
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert exc_info.value.slot_id == "m00"
    assert exc_info.value.field == "base_color"
    assert "m00" in str(exc_info.value) and "base_color" in str(exc_info.value)


def test_defect_base_color_dict_raises_avatar_meta_error():
    """base_colorが4要素以上のdict。
    修正前: `if base_color and len(base_color) >= 4` を通過してしまい、
    solid_color_key内のrgba[:4](dictのスライス)が素の例外を投げていた。
    dev#936: この裸例外の型はCPythonのバージョンに依存する(sliceがhashableに
    なったPython 3.12以降はKeyError、3.11以前はTypeError。DICT_SLICE_BARE_EXC_TYPE
    docstring参照)ため、決め打たずこのインタプリタでの実測値と比較する。
    再現: vp_atlas.plan_avatar({'slots': {'m00': {'orig_name': 'body',
    'texture': None, 'base_color': {'r':1,'g':2,'b':3,'a':4}}}})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar({
            "slots": {"m00": {"orig_name": "body", "texture": None,
                               "base_color": {"r": 1, "g": 2, "b": 3, "a": 4}}}})
    assert isinstance(exc_info.value.__cause__, DICT_SLICE_BARE_EXC_TYPE)
    assert exc_info.value.slot_id == "m00"
    assert exc_info.value.field == "base_color"
    assert "m00" in str(exc_info.value) and "base_color" in str(exc_info.value)


def test_defect_mixed_key_types_raises_avatar_meta_error():
    """slotsの辞書キーの型が混在(str/int)。
    修正前: sorted(slots.keys()) がPython3では比較不能で素のTypeErrorを
    投げていた。
    再現: vp_atlas.plan_avatar({'slots': {'m00': {...}, 1: {...}}})"""
    with pytest.raises(vp_atlas.AvatarMetaError) as exc_info:
        vp_atlas.plan_avatar({
            "slots": {
                "m00": {"orig_name": "body", "texture": "a.png"},
                1: {"orig_name": "x", "texture": "b.png"},
            }})
    assert isinstance(exc_info.value.__cause__, TypeError)
    assert exc_info.value.field == "slots"
    assert "slots" in str(exc_info.value)


# ==================================================== P2: ランダムファズ

def _mutate_type_swap(rng, value):
    """valueを別の型へ挿げ替える(型の入れ替え/配列と辞書の入れ替え)。"""
    swaps = [
        lambda v: None,
        lambda v: rng.randint(-10**18, 10**18),  # 巨大な数値を含む
        lambda v: 1e308 * rng.choice([1, -1]),
        lambda v: [v] if not isinstance(v, list) else {"wrapped": v},
        lambda v: {"unexpected": v} if not isinstance(v, dict) else [v],
        lambda v: "",
        lambda v: [[[[[v]]]]],  # 深いネスト
        lambda v: (v,) * 3,  # tuple化(dict/list想定箇所に渡す)
        # 数値のはずが文字列(base_color想定フィールド向け、WP必須の型入れ替え)
        lambda v: ["not", "a", "number", "here"],
        # 配列⇄辞書入れ替え(base_colorが4キーのdictになるケース。
        # len()>=4を満たしてしまいsolid_color_key内のスライスでKeyErrorを誘発)
        lambda v: {"r": 1, "g": 2, "b": 3, "a": 4},
    ]
    return rng.choice(swaps)(value)


def _mutate_bad_unicode(rng, s):
    """不正なコードポイント(孤立サロゲート)を混ぜた文字列を作る。"""
    bad_chars = "\udc80\udcff\ud800"
    pos = rng.randint(0, len(s))
    return s[:pos] + rng.choice(bad_chars) + s[pos:]


def _mutate_drop_required_key(rng, info):
    info = dict(info)
    key = rng.choice(["orig_name", "texture", "base_color", "alpha_mode"])
    info.pop(key, None)
    return info


def _mutate_meta_shape(rng, base_meta, n_ops):
    """base_metaを深くコピーしつつ、rngに従ってn_ops回の壊し方を適用する。
    WP指定の壊し方カテゴリを一通り経由するよう、複数の変異点(meta全体/
    slots全体/1スロットのinfo全体/フィールド単位)からランダムに選ぶ。"""
    import copy
    meta = copy.deepcopy(base_meta)

    for _ in range(n_ops):
        target = rng.choice(["meta_root", "slots_container", "slot_info",
                              "field_texture", "field_base_color",
                              "field_orig_name", "field_alpha_mode",
                              "drop_required_key"])
        if target == "meta_root":
            meta = _mutate_type_swap(rng, meta)
            if not isinstance(meta, dict):
                # 型が壊れたらそれ以上フィールド単位の変異は続けられない
                break
        elif not isinstance(meta, dict):
            break
        elif target == "slots_container":
            meta["slots"] = _mutate_type_swap(rng, meta.get("slots", {}))
        elif not isinstance(meta.get("slots"), dict) or not meta["slots"]:
            continue
        elif target == "slot_info":
            slot_id = rng.choice(list(meta["slots"].keys()))
            meta["slots"][slot_id] = _mutate_type_swap(rng, meta["slots"][slot_id])
        else:
            slot_id = rng.choice(list(meta["slots"].keys()))
            info = meta["slots"][slot_id]
            if not isinstance(info, dict):
                continue
            if target == "field_texture":
                info["texture"] = _mutate_type_swap(rng, info.get("texture", "t.png"))
            elif target == "field_base_color":
                info["base_color"] = _mutate_type_swap(rng, info.get("base_color", [0, 0, 0, 1]))
            elif target == "field_orig_name":
                info["orig_name"] = _mutate_bad_unicode(rng, str(info.get("orig_name", "body")))
            elif target == "field_alpha_mode":
                info["alpha_mode"] = _mutate_type_swap(rng, info.get("alpha_mode", "OPAQUE"))
            elif target == "drop_required_key":
                meta["slots"][slot_id] = _mutate_drop_required_key(rng, info)
    return meta


def _targeted_break_cases():
    """汎用ランダム変異だけでは低確率でしか踏まない(=200ケースでは出ない
    こともある)特定の壊し方を、決定的に確実に踏むための固定ケース集。
    KeyError(base_colorが4キー以上のdict)・ValueError(base_colorが非数値の
    要素)・TypeError(slotsキーの型混在)は、汎用変異の組み合わせ数が多く
    確率的に埋もれるため、ここで明示的に用意して「型の入れ替え」
    「配列と辞書の入れ替え」カテゴリの網羅を保証する。"""
    return [
        ("targeted_base_color_dict4keys", {
            "slots": {"m00": {"orig_name": "body", "texture": None,
                               "base_color": {"r": 1, "g": 2, "b": 3, "a": 4}}}}),
        ("targeted_base_color_non_numeric", {
            "slots": {"m00": {"orig_name": "body", "texture": None,
                               "base_color": ["a", "b", "c", "d"]}}}),
        ("targeted_mixed_key_types", {
            "slots": {"m00": {"orig_name": "body", "texture": "a.png"},
                      1: {"orig_name": "x", "texture": "b.png"}}}),
        ("targeted_slots_is_list", {"slots": [{"orig_name": "body", "texture": "a.png"}]}),
        ("targeted_info_is_string", {"slots": {"m00": "not-a-dict"}}),
        ("targeted_texture_is_int", {
            "slots": {"m00": {"orig_name": "body", "texture": 123}}}),
        ("targeted_meta_is_none", None),
    ]


def _run_fuzz(seed, n_cases, max_ops):
    rng = random.Random(seed)
    # violations要素: (case_index, meta_repr, exc_type, exc_msg, cause_type)
    # cause_type は raise ... from e で連鎖された元の裸例外の型(無ければNone)。
    violations = []
    survived = 0

    # 決定的な狙い撃ちケース(WP必須カテゴリの網羅を、確率に頼らず保証する)
    for label, meta in _targeted_break_cases():
        try:
            vp_atlas.plan_avatar(meta)
            survived += 1
        except Exception as e:  # noqa: BLE001 -- 分類が目的
            cause_type = type(e.__cause__) if e.__cause__ is not None else None
            violations.append((label, repr(meta)[:300], type(e), str(e), cause_type))

    # ランダム変異ループ(組み合わせ的な広さを担当)
    for i in range(n_cases):
        n_slots = rng.randint(0, 4)
        base_meta = _valid_meta(n_slots) if n_slots else rng.choice(
            [{}, {"slots": {}}, {"other": "x"}])
        n_ops = rng.randint(1, max_ops)
        meta = _mutate_meta_shape(rng, base_meta, n_ops)
        try:
            vp_atlas.plan_avatar(meta)
            survived += 1
        except Exception as e:  # noqa: BLE001 -- 分類が目的
            cause_type = type(e.__cause__) if e.__cause__ is not None else None
            violations.append((i, repr(meta)[:300], type(e), str(e), cause_type))
    return violations, survived


def test_plan_avatar_fuzz_stays_within_known_defect_catalog():
    """ランダムファズ本体(WP必須の壊し方一式を横断: 空/型入れ替え/配列⇄辞書/
    巨大な数値/深いネスト/不正コードポイント/必須キー欠落)。

    固定シードで7件の狙い撃ちケース+200ケース×最大3変異のランダム生成を
    行い、plan_avatarを呼ぶ。

    dev#740修正後のアサーションは3段(修正前は「裸の例外の型」を直接見て
    いたが、修正後は全て`vp_atlas.AvatarMetaError`に統一されるはずなので、
    かわりに`__cause__`(raise ... from eで連鎖された元の裸例外)の型で
    旧・欠陥カタログの横断具合を確認する):
      1. 少なくとも1件は例外(=AvatarMetaError)で落ちること
         (=このファズが実際に欠陥面を捉えている。0件なら試験として無価値)。
      2. 発生した例外が**全て**`vp_atlas.AvatarMetaError`であること
         (=裸のAttributeError/TypeError/KeyError/ValueErrorがそのまま
         漏れる退行がないこと。それ以外の型が1件でもあれば、このWPで
         直したはずの経路がまだ塞がっていないか、または未知の新しい
         壊れ方が見つかったことを意味する)。
      3. 連鎖された元例外(`__cause__`)の型が KNOWN_BARE_EXCEPTION_TYPES の
         **全種類**を最低1回は含むこと(=「型の入れ替え」「配列と辞書の
         入れ替え」「必須キー欠落」等WPが列挙した壊し方を、単発の代表例
         だけでなく実際に横断しているという根拠。加えて、修正が単に
         例外を握りつぶしただけでなく、元の診断情報を連鎖させたままである
         ことの実測でもある)。
    """
    violations, survived = _run_fuzz(FIXED_SEED, n_cases=200, max_ops=3)

    assert survived > 0, "生存ケースが1件も無い(ジェネレータが壊れている可能性)"
    assert len(violations) > 0, (
        "既知の欠陥カタログに触れるケースが1件も無かった。"
        "これはファズが対象を捉えられていない(=無価値な試験)ことを示すため、"
        "シード/変異演算子を見直すこと。"
    )

    unexpected = [(i, m, t, msg) for (i, m, t, msg, _c) in violations
                  if t is not vp_atlas.AvatarMetaError]
    assert not unexpected, (
        "dev#740修正後は、構造的に壊れたmetaは必ずvp_atlas.AvatarMetaErrorとして"
        "診断可能に送出されるべき(裸の例外が漏れる退行、または未知の壊れ方): "
        f"{[(i, t.__name__, msg) for (i, _m, t, msg) in unexpected[:5]]}"
    )

    cause_types_seen = {c for (_i, _m, _t, _msg, c) in violations if c is not None}
    missing_cause_types = set(KNOWN_BARE_EXCEPTION_TYPES) - cause_types_seen
    assert not missing_cause_types, (
        f"既知の欠陥カタログのうち "
        f"{sorted(t.__name__ for t in missing_cause_types)} が、連鎖元例外"
        "(__cause__)として一度も踏まれなかった。"
        "_targeted_break_cases()のケースが変わったか、AvatarMetaErrorへの"
        "wrapがraise...from eの連鎖を落としている可能性がある。"
    )

    print(f"[dev136-fuzz] cases={len(_targeted_break_cases())}+200 "
          f"survived={survived} violations={len(violations)} "
          f"cause_types_seen={sorted(t.__name__ for t in cause_types_seen)}")
    for i, m, t, msg, c in violations[:10]:
        cname = c.__name__ if c is not None else None
        print(f"[dev136-fuzz][violation] case={i} {t.__name__}(cause={cname}): {msg} meta={m}")


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(pytest.main([__file__, "-v"] + _sys.argv[1:]))
