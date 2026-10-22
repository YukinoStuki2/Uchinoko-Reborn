# -*- coding: utf-8 -*-
"""dev#165(2026-08-08 装備限定): 装備の表示名(日本語/英語等)をユーザーの手元の
Palworld pakから実行時に抽出するモジュール。

権利裁定(2026-08-08、dev#165コメント6項): 「装備固有名詞の実行時抽出・表示は
採用可」(dev#894はこの裁定で主目的解消につきclose)。**名称データそのものの
同梱は禁止**——本モジュールは常にユーザー自身のpakから毎回読み取るだけで、
装備名の文字列を一切ソースにハードコードしない(このファイルにもテスト
コードにも、実在の装備名を平文で書かない)。

抽出元: UEのローカライズリソース(.locres、FTextLocalizationResource形式)。
DataTable経由の抽出は本WPでは実装しない(locresで名称が取れれば装備選択
ダイアログの目的は満たせるため、実装コストの小さい方から着手した)。

L0(pipeline\\py\\extract_vanilla.py / pak_live_extract.py / vp_core.py)が
既に確立している「UnrealPak.exe不使用でPalworldのpakからその場でファイルを
抽出する」経路(pak_live_extract.extract_files())をそのまま再利用する
(新しいpak読み取り経路は作らない)。

**実pak検証済み(2026-08-08 dev#165第2弾補修)**: 本モジュールのlocres
バイナリパーサは、開発機に実在するPalworld実pak
(`Pal\\Content\\Paks\\Pal-Windows.pak`)に対して実行し、当初実装(最善努力の
未検証実装)が持っていた2箇所の構造バグ(エントリ総数フィールドの読み飛ばし
漏れ・FTextKeyのハッシュ/文字列の順序誤り)を特定・修正した。修正後は実pak中
最大級のlocres(`Engine/Content/Localization/Engine/ja/Engine.locres`、
29065エントリ、version=3)を1バイトのズレも無く終端まで正しくパースできる
ことを実測確認済み(詳細は`_parse_locres()`のdocstring参照)。

**既知の限界(パーサのバグではなく実データの構造。第4弾で解消——下記参照)**:
装備/アイテム名の候補として`_find_locres_path()`が探す`Pal/Content/
Localization/Game/<culture>/Game.locres`は、実pak確認した17言語すべてで
namespace数0の空ファイルだった。Palworldは装備/アイテムの表示名を標準
locres gatherではなくper-culture DataTableアセット(`Pal/Content/L10N/
<culture>/Pal/DataTable/Text/DT_ItemNameText_Common.uasset`+`.uexp`。
日本語は既定カルチャのため`Pal/Content/Pal/DataTable/Text/
DT_ItemNameText_Common`に有る)へ格納している。locresパーサ自体は無関係
(既存locresの他項目には引き続き使える)なので本モジュールに残すが、
装備名の解決は下記の第4弾で追加したDataTable直接パースが主経路になる。

**第4弾(2026-08-08、dev#165 UI表示名格上げ、オーナー裁定「最初から
正しい装備名で出せ」の実装)**: DT_ItemNameText_Common(FProperty/RowStruct
不要、unversioned propertiesの生バイト列を直接パース)+
DT_CharacterCreationMeshPresetTable_Equipments(装備コード→ItemIDの対応
表)を組み合わせて実際の表示名を解決する。実pak実測(2026-08-08、
`Pal-Windows.pak`、33装備コード中): 30件で一意な対応が取れ、日英とも
正しい表示名(例: Cloth001→ja"布の服"/en"Cloth Outfit")を取得できることを
確認済み。残り3件(Ancient001_v04・Iron001_v02_2・Octavia001_v01)は
複数行から同じコードが見つかる曖昧なケース、またはテーブルに参照が
無いケースで、安全側に倒して対応なし(=既存のコード表示フォールバック)
のまま。詳細は`resolve_equipment_item_ids()`のdocstring参照。

**第5弾(2026-08-08、dev#165/#277 頭装備切り替えの表示名拡張)**: 第4弾の
DataTable直接解決の枠組み(DT_CharacterCreationMeshPresetTable_Equipments
+DT_ItemNameText_Common)を頭装備(HeadEquip)にも拡張した。頭装備プリセット
行は体防具と異なり統一命名規則を持たず、また1コードに複数のプリセット行
(色/バリアント違い)が対応するのが通常のケースであるため、専用の
`resolve_headequip_item_ids()`/`_canonical_headequip_row()`(末尾"_<数字>"
の有無で基準行を選ぶ)を追加した。`resolve_display_names()`の新しい
`domain`引数("equipment"|"headequip")で切り替える(呼び出し元は
`pipeline\\py\\vp_headequip_names.py`)。実pak実測(2026-08-08、
`Pal-Windows.pak`、64頭装備コード中): 62件で一意な対応が取れ、日英中韓
5言語いずれでも正しい表示名(例: HeadEquip016→ja"金属ヘルム"/
en"Metal Helm")を取得できることを確認済み。詳細は
`resolve_headequip_item_ids()`のdocstring参照。

解析・照合・pak読み取りのいずれかが失敗しても例外は外へ伝播させない
(resolve_display_names()は常に(dict, status)を返す)。失敗時は呼び出し側が
`names.get(code, code)` で内部コード表示へフォールバックできる
(=「自動発見→失敗時フォールバック→探索ログ」の三点セット、CLAUDE.md
「外部依存パスの原則」)。

CLIとしても呼べる(GUI層=app_pyはpipeline\\pyをimportしない設計のため、
app_py側は本モジュールをsubprocessで起動しJSONを標準出力から受け取る想定):

    python vp_equipment_names.py <palworld_pak> <lang> <cache_dir> <code1,code2,...>

標準出力へ1行のJSON `{"ok": bool, "source": str, "detail": str,
"names": {code: text, ...}}` を書く。プロセスの終了コードは常に0
(失敗もJSONのok=falseで表現する——subprocessの非0終了コードだけに頼ると
「握りつぶした例外由来」なのか「何か別の理由で落ちた」なのか呼び出し側で
区別しづらいため)。ただし`extract_files`等が内部でvp_core.die()
(=sys.exit)を呼んだ場合はそちらを優先し、その終了コードのまま終わる
(try/exceptでSystemExitも捕捉しているが、捕捉しきれない想定外の場所で
die()が呼ばれた場合の保険としてこの説明を残す)。
"""
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import vp_core as core  # noqa: E402
import pak_live_extract  # noqa: E402
import vp_equipment_filter  # noqa: E402 (equipment_code()の再利用。同じpipeline\py内なので越境輸入ではない)
import vp_headequip_filter  # noqa: E402 (headequip_code()の再利用。第5弾、下記docstring参照)
import vp_exclusions  # noqa: E402 (dev#165装備限定リストからコラボ除外denylist該当装備を隠す。
                       # オーナー指示2026-08-08「ホーリープレート対策」: 選んでもvp_exclusionsの
                       # 除外集合が優先されて注入されない装備は、選択肢として出す意味が無い。
                       # 判定を1箇所(list_equipment_codes_from_pak)に集約し、除外集合の正本は
                       # 従来どおりvp_exclusions.py 1箇所に保つ(重複させない)。

TAG = "vp_equipment_names"

# パーサのロジックを変えたらここを上げる(キャッシュキーに含める。古い
# キャッシュを誤って使い続けないため)。
# 2: 第4弾(dev#165)でDataTable直接解決を追加。旧キャッシュ(locresのみ、
#    常に空)を誤って使い続けないよう上げる。
# 3: 第5弾(dev#165/#277)でresolve_display_names()に domain 引数を追加
#    (キャッシュキーにdomainを含めるようになった。equipment用キャッシュと
#    headequip用キャッシュが同じ(pak,lang)でも別ハッシュになる)。
_PARSER_VERSION = 3

# app_py/i18n.py の LANGS("ja","en","ko","zhTW","zhCN")に対応する、locres内の
# カルチャフォルダ名候補(複数候補を上から順に試す)。実際のフォルダ名は
# ゲームごとに違うため、確実な決め打ちはできない——複数候補+実在パス走査
# (_find_locres_path)の組み合わせで対処する。
_CULTURE_CANDIDATES = {
    "ja": ["ja"],
    "en": ["en"],
    "ko": ["ko"],
    "zhTW": ["zh-Hant", "zh-TW"],
    "zhCN": ["zh-Hans", "zh-CN"],
}

_LOCRES_MAGIC = bytes([0x0E, 0x14, 0x74, 0x75, 0x67, 0x4A, 0x03, 0xFC,
                        0x4A, 0x15, 0x90, 0x9D, 0xC3, 0x37, 0x7F, 0x1B])


def _culture_candidates(lang):
    return _CULTURE_CANDIDATES.get(lang, ["en"])


def _find_locres_path(all_paths, culture_candidates):
    """pak全エントリパス(vp_core.read_pak_index()の戻り値)から、候補
    カルチャのうち最初に見つかった.locresのパスを返す(無ければNone)。
    ハードコードされた固定パスへは依存せず、実在するpakエントリを走査する
    (=「自動発見」)。

    dev#165追補(2026-08-08 実pakデバッグで判明): 素朴に「カルチャ一致する
    最初の.locres」を返すと、pak内には同じカルチャの.locresがPal本体以外
    (Engine/、Engine/Plugins/配下等)にも大量にあり、走査順序次第で無関係な
    Engine.locres(装備名を含み得ない)を掴んでしまう。`Pal/`配下のエントリを
    優先する(実測: Palworld実pakには`Pal/Content/Localization/Game/<culture>/
    Game.locres`が存在する。同名locresが複数言語分あるが、いずれもPal/配下は
    1つだけなので優先すれば確実に正しい方を掴む)。Pal/配下に無いカルチャ
    だけ、フォールバックとして他の場所の一致にも当たる(0件よりは探索した
    という記録が残る方がよい)。"""
    lowered = [(p, p.lower()) for p in all_paths if p.lower().endswith(".locres")]
    for culture in culture_candidates:
        seg = f"/{culture.lower()}/"
        pal_match = None
        other_match = None
        for p, pl in lowered:
            if seg not in pl:
                continue
            if pl.startswith("pal/") and pal_match is None:
                pal_match = p
            elif other_match is None:
                other_match = p
        if pal_match is not None:
            return pal_match
        if other_match is not None:
            return other_match
    return None


def _read_fstring(buf, pos):
    """UEのFString(u32長プレフィックス。正数=ASCII全角ヌル終端、
    負数=UTF-16LEヌル終端)を読む。pipeline\\py\\vp_core.py の
    _read_fstring(stream版)と同一の規約をbytes+pos版で独立実装したもの
    (locresはランダムアクセスしながら読むためstreamでなくbytes+posの方が
    都合が良い。ロジックは同一)。戻り値: (str, new_pos)。"""
    if pos + 4 > len(buf):
        raise ValueError(f"truncated FString length at pos={pos}")
    (n,) = struct.unpack_from("<i", buf, pos)
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        end = pos + n
        if end > len(buf):
            raise ValueError(f"truncated FString(ascii) at pos={pos} n={n}")
        s = buf[pos:end - 1].decode("ascii", errors="replace")
        return s, end
    n = -n
    end = pos + n * 2
    if end > len(buf):
        raise ValueError(f"truncated FString(utf16) at pos={pos} n={n}")
    s = buf[pos:end - 2].decode("utf-16-le", errors="replace")
    return s, end


def _parse_locres(data):
    """FTextLocalizationResourceの本文をパースし、{(namespace, key): text}を
    返す。想定外の値(実在しえないカウント等)を読んだ時点でValueErrorを
    送出し、呼び出し側が握りつぶしてフォールバックする設計。

    dev#165追補(2026-08-08 実pakデバッグで実測検証済み): 当初実装
    (モジュール初版)は「未検証」の最善努力実装で、Palworld実pak
    (`C:\\...\\Palworld\\Pal\\Content\\Paks\\Pal-Windows.pak`)の
    `Engine/Content/Localization/Engine/ja/Engine.locres`(29065エントリ、
    version=3)に対して2箇所の構造バグがあり全滅していた。以下の2点を
    修正し、上記locresを1バイトのズレも無く終端(value array終端が
    ファイル末尾、namespace/keyセクション終端がvalue_array_offsetと完全
    一致)まで読み切れることを実測で確認した:

    1. **エントリ総数フィールドの読み飛ばし漏れ**: version>=2(Optimized)
       では、LocalizedStringArrayOffset(8byte)の直後に「namespace跨ぎの
       key総数」(4byte、未使用の参考値)が挟まる。旧実装はこれを
       namespace数だと誤読しており、以降の全オフセットが破綻していた。
    2. **FTextKeyのフィールド順序**: namespace名・key名はいずれも
       「ハッシュ(4byte、version>=1)が先、文字列(FString)が後」の順で
       シリアライズされる。旧実装は逆順(文字列が先)で読んでおり、
       ハッシュ値をFString長プレフィックスと誤読して巨大な長さを読もうと
       し破綻していた。

    対応バージョン: マジック無し(Legacy, version=0扱い) / マジック有り
    version 1(Compact)以上(namespace/keyの前に4byteのハッシュが1つ
    挟まる) / version 2以上(Optimized: ローカライズ文字列は本体から
    切り離された配列に重複排除格納され、キー側は配列インデックスだけを
    持つ)。version 3(Optimized_CityHash64_UTF16)の差分はこのハッシュ
    アルゴリズム自体(本パーサは未使用のハッシュ値を読み捨てるだけなので
    影響しない)。

    **既知の限界(2026-08-08実測、パーサのバグではない)**: 上記の修正で
    パーサ自体は実pakの大規模locresを正しく読めることを確認したが、
    Palworldが実際に出荷している装備/アイテム名の候補locres
    (`Pal/Content/Localization/Game/<culture>/Game.locres`)は、確認した
    17言語すべてで37バイト・namespace数0の**空ファイル**だった
    (この事実はパーサの新旧いずれでも変わらない=構造上の空)。実際の
    装備/アイテム表示名は、UEの標準locres gatherではなく、per-culture
    DataTableアセット(`Pal/Content/L10N/<culture>/Pal/DataTable/Text/
    DT_ItemNameText_Common.uasset`+`.uexp`。日本語は既定カルチャのため
    L10Nオーバーライドを持たず`Pal/Content/Pal/DataTable/Text/
    DT_ItemNameText_Common.uasset`+`.uexp`に有る)に格納されている。
    このDataTable形式はFProperty/RowStructを解釈するUE DataTableパーサが
    別途必要で、本モジュール初版の設計判断どおり本WPでも実装しない
    (dev#165本体のissueコメントで追跡)。したがって
    `resolve_display_names()`は実pakに対して`ok=False`
    (`source="locres"`, 一致0件)を返し続けるが、これはパーサが壊れて
    いるのではなく実データが無いことの正しい報告であり、既存の
    フォールバック(`names.get(code, code)`)がそのまま機能する。"""
    pos = 0
    version = 0
    if data[:16] == _LOCRES_MAGIC:
        pos = 16
        if pos >= len(data):
            raise ValueError("truncated locres header (magic but no version byte)")
        version = data[pos]
        pos += 1

    value_array_offset = None
    if version >= 2:
        if pos + 8 > len(data):
            raise ValueError("truncated locres header (missing value array offset)")
        (value_array_offset,) = struct.unpack_from("<Q", data, pos)
        pos += 8
        if value_array_offset >= len(data):
            raise ValueError(f"value array offset out of range: {value_array_offset}")
        if pos + 4 > len(data):
            raise ValueError("truncated locres header (missing entries count)")
        pos += 4  # エントリ総数(namespace跨ぎのkey総数、未使用、読み捨て)

    result = {}
    value_refs = []  # [(namespace, key, string_index), ...] (version>=2のみ)

    if pos + 4 > len(data):
        raise ValueError("truncated locres header (missing namespace count)")
    (num_ns,) = struct.unpack_from("<i", data, pos)
    pos += 4
    if not (0 <= num_ns <= 200000):
        raise ValueError(f"implausible namespace count: {num_ns}")

    for _ in range(num_ns):
        if version >= 1:
            if pos + 4 > len(data):
                raise ValueError("truncated namespace key hash")
            pos += 4  # namespace key hash(未使用、読み捨て。文字列より先)
        ns, pos = _read_fstring(data, pos)
        if pos + 4 > len(data):
            raise ValueError(f"truncated key count for namespace={ns!r}")
        (num_keys,) = struct.unpack_from("<i", data, pos)
        pos += 4
        if not (0 <= num_keys <= 500000):
            raise ValueError(f"implausible key count: {num_keys} (namespace={ns!r})")
        for _ in range(num_keys):
            if version >= 1:
                if pos + 4 > len(data):
                    raise ValueError(f"truncated key hash (namespace={ns!r})")
                pos += 4  # key hash(未使用、読み捨て。文字列より先)
            key, pos = _read_fstring(data, pos)
            if pos + 4 > len(data):
                raise ValueError(f"truncated source string hash (namespace={ns!r} key={key!r})")
            pos += 4  # source string hash(未使用、読み捨て。バージョン不問で常に存在)
            if version >= 2:
                if pos + 4 > len(data):
                    raise ValueError(f"truncated string index (namespace={ns!r} key={key!r})")
                (string_index,) = struct.unpack_from("<i", data, pos)
                pos += 4
                value_refs.append((ns, key, string_index))
            else:
                text, pos = _read_fstring(data, pos)
                result[(ns, key)] = text

    if version >= 2:
        vpos = value_array_offset
        if vpos + 4 > len(data):
            raise ValueError("truncated value array (missing count)")
        (count,) = struct.unpack_from("<i", data, vpos)
        vpos += 4
        if not (0 <= count <= 1000000):
            raise ValueError(f"implausible value array count: {count}")
        strings = []
        for _ in range(count):
            s, vpos = _read_fstring(data, vpos)
            if vpos + 4 > len(data):
                raise ValueError("truncated value array (missing ref count)")
            vpos += 4  # ref count(未使用、読み捨て)
            strings.append(s)
        for ns, key, idx in value_refs:
            if 0 <= idx < len(strings):
                result[(ns, key)] = strings[idx]
    return result


def _match_equipment_names(parsed, equipment_codes):
    """{(namespace,key):text} から装備コード集合に一致しそうな表示名を拾う。
    locres内のキー命名規則(装備SKの内部コードと一致する保証は無い、
    モジュールdocstring参照)が不明なため、複数のゆるい照合(完全一致/
    アンダースコア区切りの末尾一致/そのままの末尾一致、いずれも大小無視)を
    順に試す。1コードにつき最初に見つかった空でないテキストを採用する。"""
    codes_lower = {c.lower(): c for c in equipment_codes}
    out = {}
    for (_ns, key), text in parsed.items():
        if not text:
            continue
        key_lower = key.lower()
        for cl, orig in codes_lower.items():
            if orig in out:
                continue
            if key_lower == cl or key_lower.endswith("_" + cl) or key_lower.endswith(cl):
                out[orig] = text
    return out


def list_equipment_codes_from_pak(pak_path):
    """live_template.build_live_template()(700MB抽出)のような重いテンプレート
    組み立てを経由せず、pakのエントリ一覧(vp_core.read_pak_index、既に
    resolve_display_names()がlocres探索で使うのと同じ読み取り)だけから
    装備コードの集合を求める。装備選択ダイアログを開く時点ではまだ変換
    ジョブが走っていない(=変換用に解決済みのテンプレートディレクトリが
    存在しない)ことが普通なので、この軽量経路が必要。

    実際の注入対象との一致は vp_equipment_filter.list_outfit_sk_names()
    (変換時、解決済みテンプレートディレクトリに対して同じ
    equipment_code()判定を使う)側で保証される——両者は「.uexpのbasenameに
    対してequipment_code()を通す」という同じルールを共有しているだけで、
    実装を複製してはいない。"""
    try:
        _mount, all_paths = core.read_pak_index(pak_path)
    except SystemExit as e:
        raise RuntimeError(f"pak index read aborted (exit={e.code})") from e
    codes = set()
    for p in all_paths:
        pl = p.replace("\\", "/").lower()
        if "/player/outfit/" not in pl or not pl.endswith(".uexp"):
            continue
        base = os.path.basename(p)[:-len(".uexp")]
        if vp_exclusions.is_excluded(base):
            # dev#165(2026-08-08オーナー指示): コラボ除外denylist該当装備
            # (例: Yakushima001="ホーリープレート")は選んでも
            # vp_exclusions側の除外が優先されて注入されない(is_excluded()は
            # equipment_filterの選択より強い)。選択リストに出す意味が無い
            # ので、カタログ列挙の時点で隠す(表示のみの変更。既存の
            # equipment_filter/known_equipment_codes側の絞り込みロジックは
            # 変更しない=選んでも選ばなくても最終結果は従来どおり不変)。
            continue
        code = vp_equipment_filter.equipment_code(base)
        if code is not None:
            codes.add(code)
    return codes


def _fingerprint(pak_path, lang, domain="equipment"):
    """キャッシュの鍵(extract_vanilla.build_fingerprint()と同じ流儀:
    pakの絶対パス+サイズ+更新時刻。40GB超のpak自体はハッシュしない)。

    domain(第5弾、dev#165/#277追補): "equipment"(体防具、既定)/
    "headequip"(頭防具)。同じ(pak,lang)でも体防具用キャッシュと頭防具用
    キャッシュが別ハッシュになるようにする(resolve_display_names()が
    domainごとに異なるresolverを使うため、キャッシュを取り違えると
    「求めたコードが1件も無いキャッシュ」を誤ってヒットしてしまう
    ——headequip呼び出しがequipment側の古いキャッシュを掴んで
    source="cache", names={} を返す事故を構造的に防ぐ)。既定値は
    "equipment"(体防具用の既存呼び出しはdomainを渡さなくてよい)。"""
    st = os.stat(pak_path)
    h = hashlib.sha256()
    h.update(f"{os.path.abspath(pak_path)}|{st.st_size}|{st.st_mtime}|"
             f"{lang}|{domain}|{_PARSER_VERSION}".encode("utf-8"))
    return h.hexdigest()[:24]


def _resolve_via_locres(pak_path, lang, equipment_codes, all_paths):
    """旧経路(第1〜3弾、モジュールdocstring参照): locres探索+ゆるい
    キー照合。実pak上のPalworld装備名は現状ここでは見つからない
    (`Pal/Content/Localization/Game/<culture>/Game.locres`が空ファイル
    のため)が、locresパーサ自体は他項目に使い得る一般実装なので
    第4弾(DataTable直接解決)で解決できなかったコードの補助経路として
    残す。どんな失敗でも例外を投げない。"""
    culture_candidates = _culture_candidates(lang)
    locres_path = _find_locres_path(all_paths, culture_candidates)
    if locres_path is None:
        return {}, {"ok": False, "source": "none",
                     "detail": f"no .locres found for culture candidates="
                                f"{culture_candidates} (searched {len(all_paths)} pak entries)",
                     "locres_path": None}

    try:
        extracted = pak_live_extract.extract_files(pak_path, [locres_path])
        data = extracted[locres_path]
        parsed = _parse_locres(data)
    except SystemExit as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"locres extraction aborted (exit={e.code}): {locres_path}",
                     "locres_path": locres_path}
    except Exception as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"locres parse failed ({type(e).__name__}: {e}): {locres_path}",
                     "locres_path": locres_path}

    names = _match_equipment_names(parsed, equipment_codes)
    ok = bool(names)
    return names, {"ok": ok, "source": "locres",
                    "detail": f"parsed {len(parsed)} locres entries, "
                               f"matched {len(names)}/{len(equipment_codes)} requested code(s)",
                    "locres_path": locres_path}


# ---------------------------------------------------------------------------
# 第4弾(2026-08-08、dev#165): DT_ItemNameText_Common + DT_CharacterCreation
# MeshPresetTable_Equipments によるDataTable直接解決(FProperty/RowStructの
# 完全なスキーマ解釈=usmap必須のパーサは書かない。両テーブルとも
# unversioned properties(cooked、スキーマ情報がuasset内に無い)だが、必要
# なのは「装備コード→ItemID」「ItemID→表示名」の2つの対応表だけなので、
# 既知の構造的アンカー(RowNameのFName、既知のリテラル文字列)を手がかりに
# した最小限のバイナリスキャンで足りる。手法は本ファイル既存の
# find_refskeleton()/vp_core.find_refskeleton()と同じ「フィンガープリント
# 走査」路線(usmap不要、実測検証済み)。
# ---------------------------------------------------------------------------

# DT_CharacterCreationMeshPresetTable_EquipmentsのNameMapのうち、行名
# (RowName)候補から除外する「アセットのbasename」プレフィックス(UEの
# 慣習的な種別接頭辞)。行名自体はこれらのいずれのプレフィックスも
# 持たない(ClothArmor・IronArmor・Player_Outfit_Kigurumi001等)。
_MESH_PRESET_ASSET_PREFIXES = ("SK_", "ABP_", "T_", "MI_", "M_", "PHYS_", "BP_", "MPC_")


def _read_name_map_from_bytes(uasset_data):
    """core.read_names()のbytes版(独立実装。モジュール冒頭docstring
    「pipeline\\py\\vp_core.pyの...版を...独立実装したもの」の方針を
    踏襲——pak_live_extract.extract_files()はbytesを返すため、一時
    ファイルを経由せずそのままNameMapを読めるようにする)。"""
    if struct.unpack_from("<I", uasset_data, 0)[0] != 0x9E2A83C1:
        raise ValueError("uasset magic mismatch")
    pos = 4
    legacy_ver = struct.unpack_from("<i", uasset_data, pos)[0]
    pos += 4
    if legacy_ver != -4:
        pos += 4  # LegacyUE3Version
    pos += 4  # FileVersionUE4
    if legacy_ver <= -8:
        pos += 4  # FileVersionUE5
    pos += 4  # FileVersionLicenseeUE
    (cv_count,) = struct.unpack_from("<i", uasset_data, pos)
    pos += 4
    if not (0 <= cv_count <= 200):
        raise ValueError(f"implausible CustomVersion count: {cv_count}")
    pos += cv_count * 20
    pos += 4  # TotalHeaderSize
    _pkg_name, pos = _read_fstring(uasset_data, pos)
    pos += 4  # PackageFlags
    name_count, name_offset = struct.unpack_from("<ii", uasset_data, pos)
    if not (0 <= name_count <= 500000) or not (0 <= name_offset < len(uasset_data)):
        raise ValueError(f"implausible NameMap header: count={name_count} offset={name_offset}")

    names = []
    pos = name_offset
    for _ in range(name_count):
        s, pos = _read_fstring(uasset_data, pos)
        pos += 4  # precalc hash(未使用)
        names.append(s)
    return names


def _is_mesh_preset_row_candidate(name):
    """DT_CharacterCreationMeshPresetTable_EquipmentsのNameMapエントリから
    「行名(RowName)候補」らしきものだけを残す。除外対象: パス文字列
    (SoftObjectPath等、'/'を含む)・Blueprintクラス参照(末尾'_C')・
    アセットのbasename(SK_/ABP_/T_/MI_等)。

    候補は装備系(ClothArmor等)にも無関係な行(頭装備プリセット等)にも
    絞らない——行境界(=次の行の開始位置)を正しく求めるには全種別の
    行を走査する必要がある(装備系だけに絞ると除外した行の分だけ
    バイト列上の境界がズレ、隣接行のデータを誤って読み込む)。"""
    if not name or "/" in name or name in ("-", "None"):
        return False
    if name.endswith("_C"):
        return False
    return not name.startswith(_MESH_PRESET_ASSET_PREFIXES)


def _is_body_armor_preset_row(name):
    """行名候補のうち、Player/Outfit(体防具)のプリセットらしいものだけを
    残す(頭防具・ヘアプリセット等のノイズを除外——実測: これらの行にも
    体防具のメッシュ参照が紛れ込むことがあり、境界誤認識でないか確証が
    持てないため、体防具の命名規則に一致する行だけを対象にする)。"""
    return ("Armor" in name) or name.startswith("Player_Outfit_") or name == "Default_EquipBody"


def _mesh_preset_row_spans(names, uexp_data):
    """DT_CharacterCreationMeshPresetTable_EquipmentsのuexpをRowName
    (FName: index+number、8byte)のバイトパターンでフィンガープリント
    走査し、行名→(開始offset,終了offset)を返す(実測検証済み手法、
    モジュールdocstring参照)。

    number!=0の行名(重複サフィックス付き)はこのテーブルには存在しない
    前提(実測確認済み)。同一(index,0)パターンが複数出現する候補は
    誤検出の疑いがあるため除外する(安全側)。"""
    anchors = []
    for i, name in enumerate(names):
        if not _is_mesh_preset_row_candidate(name):
            continue
        pat = struct.pack("<ii", i, 0)
        first = uexp_data.find(pat)
        if first == -1:
            continue
        if uexp_data.find(pat, first + 1) != -1:
            continue
        anchors.append((first, name))
    anchors.sort(key=lambda t: t[0])
    spans = {}
    for j, (off, name) in enumerate(anchors):
        end = anchors[j + 1][0] if j + 1 < len(anchors) else len(uexp_data)
        spans[name] = (off, end)
    return spans


def _row_sk_paths(names, uexp_data, spans, path_predicate, stop_at_first=False):
    """resolve_equipment_item_ids()/resolve_headequip_item_ids()共通の
    低レベル走査(第5弾、dev#165/#277で分離)。spans(_mesh_preset_row_
    spans()の戻り値、または呼び出し側で絞り込んだ部分集合)の各行のバイト
    範囲内をFName(index,number)のパターンで走査し、path_predicate(sk_path)
    がTrueを返すNameMapエントリを`[(rowname, sk_path), ...]`で返す。
    行の絞り込み(体防具限定/頭防具限定等)・変換後コードの曖昧判定は
    いずれも呼び出し側の責務(ここでは行わない)。

    stop_at_first(実測で分岐が必要と判明、両方式を維持):
      - False(既定、resolve_equipment_item_idsが使う): 1行の中に複数の
        SKパス参照が存在しうる前提で全件を返す。体防具プリセット行は
        _is_body_armor_preset_rowで事前に絞り込まれた「信頼できる行」
        だけを対象にするため、この全件収集で安全にAncient/Bronze等の
        通常/耐熱/耐寒バリアントを漏らさず拾える(元実装の挙動そのもの。
        最初の1件で打ち切ると実pakで30/33→28/33に後退することを実測
        確認済み)。
      - True(resolve_headequip_item_idsが使う): 頭装備プリセット行は
        事前絞り込みフィルタを持たず(_is_mesh_preset_row_candidateの
        緩い許可リストだけで、行境界の誤認識——ある行のspanの末尾に
        隣接する別行のデータが紛れ込む——を防ぎきれない)、全件収集だと
        本来無関係な2件目以降の参照が"canonical row"の一意性判定を
        崩して大量に対応不能化する(実測: 全件収集だと62/64→43/64に
        後退。最初の1件だけを採用する方が安全側に働く)。"""
    n_names = len(names)
    matches = []
    for rowname, (off, end) in spans.items():
        span = uexp_data[off:end]
        for o in range(0, len(span) - 8):
            vidx, vnum = struct.unpack_from("<ii", span, o)
            if 0 <= vidx < n_names and 0 <= vnum < 1000:
                nm = names[vidx]
                if path_predicate(nm):
                    matches.append((rowname, nm))
                    if stop_at_first:
                        break
    return matches


def resolve_equipment_item_ids(mesh_preset_uasset, mesh_preset_uexp):
    """装備コード(vp_equipment_filter.equipment_code()の戻り値、例
    "Cloth001")→DT_ItemNameText_CommonのItemID(例"ClothArmor")の対応表を、
    DT_CharacterCreationMeshPresetTable_Equipmentsの生バイト列(bytes、
    pak_live_extract.extract_files()の戻り値をそのまま渡せる)から求める。

    各行(体防具プリセットの命名規則に一致する行のみ、_is_body_armor_
    preset_row参照)のバイト範囲内を_row_sk_paths()で走査し、
    '/Outfit/SK_Player_'を含むパスに解決できたものを
    vp_equipment_filter.equipment_code()にかけて装備コードへ変換する。
    1つの装備コードが複数の行から見つかった場合(実測: ごく一部の特殊
    衣装で発生。境界誤認識の疑いを否定できない)は、確実性より安全性を
    優先しその装備コードの対応を採用しない(=呼び出し側のフォールバック
    へ委ねる)。

    実pak実測(2026-08-08、Pal-Windows.pak): 33装備コード中30件で一意な
    対応が取れることを確認済み(残り3件は本関数の設計上、意図的に対応
    なし——Ancient001_v04/Octavia001_v01は複数行から見つかる曖昧ケース、
    Iron001_v02_2はテーブルに参照が無いケース)。

    どんな失敗でも例外を投げない設計はここでは取らない(呼び出し側
    `_resolve_via_datatable()`がtry/exceptで包む)。

    第5弾(dev#165/#277)追補: 内部走査ロジックを_row_sk_paths()へ分離し、
    resolve_headequip_item_ids()と共有した(本関数の出力・挙動は不変。
    実pak再実測で30/33件のまま変化していないことを確認済み)。"""
    names = _read_name_map_from_bytes(mesh_preset_uasset)
    spans = _mesh_preset_row_spans(names, mesh_preset_uexp)
    body_spans = {r: s for r, s in spans.items() if _is_body_armor_preset_row(r)}
    row_sk_matches = _row_sk_paths(names, mesh_preset_uexp, body_spans,
                                    lambda nm: "/Outfit/SK_Player_" in nm)

    code_to_rows = {}
    for rowname, nm in row_sk_matches:
        code = vp_equipment_filter.equipment_code(nm)
        if code:
            code_to_rows.setdefault(code, set()).add(rowname)

    return {code: next(iter(rows)) for code, rows in code_to_rows.items() if len(rows) == 1}


_HEADEQUIP_VARIANT_SUFFIX_RE = re.compile(r"^.+_\d+$")


def _canonical_headequip_row(rownames):
    """頭防具系プリセット行群(同一SKメッシュを参照する複数行の集合)から、
    実際のItemID候補として使う「基準行」を1つ選ぶ(第5弾、dev#165/#277)。

    実pak実測(2026-08-08、Pal-Windows.pak): DT_CharacterCreationMeshPreset
    Table_Equipmentsの頭防具プリセットは、体防具と異なり「無印の行1つ+
    末尾が"_<数字>"の色/バリアント違いプリセット行が複数」という命名規則
    (例: "CopperHelmet"+"CopperHelmet_2"〜"_5"、"Head002"+"Head002_1"〜
    "_5")を取る。無印行(末尾が"_<数字>"でない)がちょうど1つあれば、それが
    実際のItemID(DT_ItemNameText_Commonのキー)と一致することを実測
    確認済み(64頭装備コード中62件で日英中韓いずれの言語でも正しい表示名
    が引けた)。

    無印行が0個(全行が末尾"_<数字>")または2個以上(同じSKメッシュを複数の
    無印行が参照している=境界誤認識、または本当に複数のプリセットが同じ
    メッシュを共有している疑い)の場合は、確実性より安全性を優先しNoneを
    返す(=呼び出し側のフォールバックへ委ねる、resolve_equipment_item_ids
    の「1コード1行」安全策と同じ思想)。実測: HeadEquip040がこのケースに
    該当する(頭防具プリセット行"GYM_Head_Sakurajima"と、着ぐるみ衣装の
    体防具プリセット行"Player_Outfit_Kigurumi001"が同じSKメッシュを参照
    しており、無印行が2つになる)。"""
    canonical = [r for r in rownames if not _HEADEQUIP_VARIANT_SUFFIX_RE.match(r)]
    if len(canonical) == 1:
        return canonical[0]
    return None


def resolve_headequip_item_ids(mesh_preset_uasset, mesh_preset_uexp):
    """頭装備コード(vp_headequip_filter.headequip_code()の戻り値、例
    "HeadEquip016")→DT_ItemNameText_CommonのItemID(例"CopperHelmet")の
    対応表を、DT_CharacterCreationMeshPresetTable_Equipmentsの生バイト列
    から求める(resolve_equipment_item_ids()の頭装備版、第5弾、
    dev#165/#277「頭装備切り替え」表示名の実装)。

    体防具(resolve_equipment_item_ids)との違い:
      - 行の絞り込みに_is_body_armor_preset_row相当のフィルタを使わない
        (頭装備プリセット行はArmor/Player_Outfit_のような統一命名規則を
        持たない——ClothHat/CopperHelmet/Head001/GYM_Head_Grass等、行名の
        語彙がバラバラで、体防具のように命名規則で安全に絞り込めない)。
        代わりに参照先パスが"/Game/"始まりかつ"/HeadEquip/"を含むことだけ
        を条件にする(_row_sk_paths()のpath_predicate)。
      - 1コードに複数行が対応するのが**通常のケース**(色/バリアント
        プリセット)。「1行だけ」を要求する体防具側とは逆に、
        _canonical_headequip_row()で「末尾が"_<数字>"でない行」を基準行
        として選ぶ。

    実pak実測(2026-08-08、Pal-Windows.pak): 64頭装備コード中62件で
    一意な対応が取れ、日英中韓5言語いずれでも正しい表示名(例:
    HeadEquip016->CopperHelmet->ja"金属ヘルム"/en"Metal Helm"/
    ko"금속 투구"/zhTW"金屬頭盔"/zhCN"金属头盔")を取得できることを確認
    済み。残り2件は安全側で対応なし(既存のコード表示フォールバックの
    まま):
      - HeadEquip040: _canonical_headequip_row()のdocstring参照(無印行が
        頭防具・体防具の2系統から見つかる曖昧ケース)
      - HeadEquip014: DT_CharacterCreationMeshPresetTable_Equipments自体に
        このSKメッシュを参照する行が1つも無い(パーサのバグではなく実
        データにプリセット行が存在しない。330行の全ダンプでも同じ結果を
        確認済み)

    どんな失敗でも例外を投げない設計はここでは取らない(呼び出し側
    `_resolve_via_datatable()`がtry/exceptで包む、resolve_equipment_
    item_idsと同じ)。"""
    names = _read_name_map_from_bytes(mesh_preset_uasset)
    spans = _mesh_preset_row_spans(names, mesh_preset_uexp)
    row_sk_matches = _row_sk_paths(
        names, mesh_preset_uexp, spans,
        lambda nm: nm.startswith("/Game/") and "/HeadEquip/" in nm,
        stop_at_first=True)

    code_to_rows = {}
    for rowname, nm in row_sk_matches:
        base = nm.rsplit("/", 1)[-1]
        code = vp_headequip_filter.headequip_code(base)
        if code:
            code_to_rows.setdefault(code, set()).add(rowname)

    resolved = {}
    for code, rows in code_to_rows.items():
        canonical = _canonical_headequip_row(rows)
        if canonical:
            resolved[code] = canonical
    return resolved


def _find_item_name_text(item_name_uexp, table_name, item_id):
    """DT_ItemNameText_Common(またはL10N版)のuexp生バイト列から、指定
    item_idの表示名(FTextのSourceString)を直接検索する(全行を走査
    せず、Key文字列"ITEM_NAME_{item_id}_TextData"のliteral一致を1件だけ
    探す——KISS、モジュールdocstring参照)。誤マッチ防止のため、その
    直前にNamespace(=table_name、この行の直前に隣接して直列化される。
    実測確認済み)が近接して存在することを確認する。

    見つからない/検証NG/デコード失敗はいずれもNoneを返す(例外は
    投げない)。"""
    if not item_id or not item_id.isascii():
        return None
    key_bytes = f"ITEM_NAME_{item_id}_TextData".encode("ascii")
    key_needle = struct.pack("<i", len(key_bytes) + 1) + key_bytes + b"\x00"
    ns_bytes = table_name.encode("ascii")
    ns_needle = struct.pack("<i", len(ns_bytes) + 1) + ns_bytes + b"\x00"

    pos = item_name_uexp.find(key_needle)
    if pos == -1:
        return None
    window_start = max(0, pos - len(ns_needle) - 16)
    if ns_needle not in item_name_uexp[window_start:pos]:
        return None
    after = pos + len(key_needle)
    try:
        text, _ = _read_fstring(item_name_uexp, after)
    except (ValueError, struct.error, IndexError):
        return None
    return text or None


_ITEM_NAME_TABLE_BASENAME = "DT_ItemNameText_Common"


def _find_mesh_preset_table_paths(all_paths):
    """pak全エントリパスからDT_CharacterCreationMeshPresetTable_Equipments
    の.uasset/.uexpを自動発見する(固定パス決め打ちを避ける——CLAUDE.md
    「外部依存パスの原則」)。見つからなければ(None, None)。"""
    uasset = uexp = None
    needle = "/dt_charactercreationmeshpresettable_equipments"
    for p in all_paths:
        pl = p.replace("\\", "/").lower()
        if not pl.endswith(needle + ".uasset") and not pl.endswith(needle + ".uexp"):
            continue
        if pl.endswith(".uasset"):
            uasset = p
        else:
            uexp = p
    return uasset, uexp


def _find_item_name_table_paths(all_paths, culture_candidates):
    """culture_candidatesの順に、DT_ItemNameText_Common.uasset/.uexpを
    探す。既定カルチャ(日本語)は`Pal/Content/Pal/DataTable/Text/`直下、
    他言語は`Pal/Content/L10N/<culture>/Pal/DataTable/Text/`配下にある
    (locres探索(_find_locres_path)と同様、固定パスではなくpak全エントリを
    走査する)。既定カルチャはL10Nフォルダを持たない(L10Nは既定からの
    差分格納のため)ので、L10N側で一致が無ければ既定側にフォールバックする。
    見つからなければ(None, None)。"""
    lowered = [(p, p.replace("\\", "/").lower()) for p in all_paths]
    suffix_uasset = "/dt_itemnametext_common.uasset"
    suffix_uexp = "/dt_itemnametext_common.uexp"

    base_uasset = base_uexp = None
    for p, pl in lowered:
        if pl == "pal/content/pal/datatable/text/dt_itemnametext_common.uasset":
            base_uasset = p
        elif pl == "pal/content/pal/datatable/text/dt_itemnametext_common.uexp":
            base_uexp = p

    for culture in culture_candidates:
        seg = f"/l10n/{culture.lower()}/"
        u_uasset = u_uexp = None
        for p, pl in lowered:
            if seg not in pl:
                continue
            if pl.endswith(suffix_uasset):
                u_uasset = p
            elif pl.endswith(suffix_uexp):
                u_uexp = p
        if u_uasset and u_uexp:
            return u_uasset, u_uexp

    if base_uasset and base_uexp:
        return base_uasset, base_uexp
    return None, None


def _resolve_via_datatable(pak_path, lang, equipment_codes, all_paths,
                            item_id_resolver=resolve_equipment_item_ids):
    """DT_CharacterCreationMeshPresetTable_Equipments(装備コード→ItemID)
    +DT_ItemNameText_Common(ItemID→表示名)を組み合わせて装備の表示名を
    解決する(dev#165第4弾、PR #1197調査の知見+実pakデバッグの実装)。
    どんな失敗でも例外を投げず(names, status)を返す。

    item_id_resolver(第5弾、dev#165/#277追補): 「装備コード→ItemID」の
    対応表を求める関数(mesh_preset_uasset, mesh_preset_uexpを受け取り
    dictを返す)。既定はresolve_equipment_item_ids(体防具)、頭防具
    呼び出しはresolve_headequip_item_idsを渡す(resolve_display_names()の
    domain引数から選択される)。DT自体の発見・抽出・ItemID→表示名解決
    ロジックはdomainによらず完全に共有する。"""
    mesh_uasset_p, mesh_uexp_p = _find_mesh_preset_table_paths(all_paths)
    if not mesh_uasset_p or not mesh_uexp_p:
        return {}, {"ok": False, "source": "none",
                     "detail": "DT_CharacterCreationMeshPresetTable_Equipments "
                               "not found in pak", "locres_path": None}

    culture_candidates = _culture_candidates(lang)
    item_uasset_p, item_uexp_p = _find_item_name_table_paths(all_paths, culture_candidates)
    if not item_uasset_p or not item_uexp_p:
        return {}, {"ok": False, "source": "none",
                     "detail": f"DT_ItemNameText_Common not found for culture "
                               f"candidates={culture_candidates}", "locres_path": None}

    try:
        extracted = pak_live_extract.extract_files(
            pak_path, [mesh_uasset_p, mesh_uexp_p, item_uexp_p])
    except SystemExit as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"datatable extraction aborted (exit={e.code})",
                     "locres_path": None}
    except Exception as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"datatable extraction failed ({type(e).__name__}: {e})",
                     "locres_path": None}

    try:
        code_to_item = item_id_resolver(
            extracted[mesh_uasset_p], extracted[mesh_uexp_p])
    except Exception as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"mesh preset table parse failed "
                               f"({type(e).__name__}: {e})", "locres_path": None}

    item_name_uexp = extracted[item_uexp_p]
    names = {}
    unresolved_item_ids = []
    for code in equipment_codes:
        item_id = code_to_item.get(code)
        if not item_id:
            continue
        text = _find_item_name_text(item_name_uexp, _ITEM_NAME_TABLE_BASENAME, item_id)
        if text:
            names[code] = text
        else:
            unresolved_item_ids.append(f"{code}->{item_id}")

    ok = bool(names)
    detail = (f"mesh preset table: {len(code_to_item)} code->item_id mapping(s), "
              f"matched {len(names)}/{len(equipment_codes)} requested code(s)")
    if unresolved_item_ids:
        detail += f"; item_id resolved but text lookup failed for: {unresolved_item_ids[:5]}"
    return names, {"ok": ok, "source": "datatable", "detail": detail, "locres_path": None}


_DATATABLE_RESOLVERS = {
    "equipment": resolve_equipment_item_ids,
    "headequip": resolve_headequip_item_ids,
}


def resolve_display_names(pak_path, lang, equipment_codes, cache_dir, domain="equipment"):
    """戻り値: (names: {code: text}(見つかった分のみ、見つからないコードは
    キーごと欠落), status: dict)。

    status = {"ok": bool, "source": "cache"|"datatable"|"locres"|
              "datatable+locres"|"none", "detail": str(人間可読の診断),
              "locres_path": str|None}

    どんな失敗でも例外を投げない。ゲームバージョンごとにcache_dir配下へ
    JSONキャッシュを持つ(毎回パースし直さない、WP指示書「ゲームバージョン
    ごとにキャッシュ」)。主経路はDataTable直接解決(第4弾)、それで
    見つからなかったコードだけlocres経路(第1〜3弾)へ補助的に回す。

    domain(第5弾、dev#165/#277追補): "equipment"(体防具、既定)/
    "headequip"(頭防具)。DT_CharacterCreationMeshPresetTable_Equipments
    から「コード→ItemID」を求める段だけdomainごとに異なるresolver
    (_DATATABLE_RESOLVERS)を使う——それ以外(パス発見・pak抽出・
    ItemID→表示名解決・locres補助経路・キャッシュ機構)は完全に共有する。
    未知のdomain文字列を渡した場合は"equipment"として扱う(安全側の既定)。
    vp_headequip_names.pyがdomain="headequip"で本関数を呼ぶ。"""
    equipment_codes = sorted(set(equipment_codes))
    if not equipment_codes:
        return {}, {"ok": True, "source": "none",
                     "detail": "no equipment codes requested", "locres_path": None}

    item_id_resolver = _DATATABLE_RESOLVERS.get(domain, resolve_equipment_item_ids)

    try:
        fp = _fingerprint(pak_path, lang, domain)
    except OSError as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"cannot stat pak: {pak_path} ({e})",
                     "locres_path": None}

    cache_file = os.path.join(cache_dir, f"names_{fp}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                cached = json.load(f)
            cached_names = cached.get("names", {})
            names = {c: cached_names[c] for c in equipment_codes if c in cached_names}
            return names, {"ok": True, "source": "cache",
                            "detail": f"cache hit: {cache_file}",
                            "locres_path": cached.get("locres_path")}
        except Exception as e:
            print(f"[{TAG}][WARN] cache file unreadable, re-extracting: "
                  f"{cache_file} ({type(e).__name__}: {e})")

    try:
        _mount, all_paths = core.read_pak_index(pak_path)
    except SystemExit as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"pak index read aborted (exit={e.code}): {pak_path}",
                     "locres_path": None}
    except Exception as e:
        return {}, {"ok": False, "source": "none",
                     "detail": f"pak index read failed ({type(e).__name__}: {e}): {pak_path}",
                     "locres_path": None}

    dt_names, dt_status = _resolve_via_datatable(
        pak_path, lang, equipment_codes, all_paths, item_id_resolver)
    remaining = [c for c in equipment_codes if c not in dt_names]
    if remaining:
        locres_names, locres_status = _resolve_via_locres(pak_path, lang, remaining, all_paths)
    else:
        locres_names, locres_status = {}, {
            "ok": True, "source": "none",
            "detail": "all requested codes already resolved via datatable",
            "locres_path": None}

    names = {**locres_names, **dt_names}  # dtがremaining除外済みなので衝突しない
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"names": names, "locres_path": locres_status.get("locres_path"),
                       "fingerprint": fp}, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[{TAG}][WARN] could not write cache (non-fatal): {cache_file} ({e})")

    if dt_names and locres_names:
        source = "datatable+locres"
    elif dt_names:
        source = "datatable"
    elif locres_names:
        source = "locres"
    else:
        source = "none"
    ok = bool(names)
    detail = f"datatable: {dt_status.get('detail')} | locres: {locres_status.get('detail')}"
    return names, {"ok": ok, "source": source, "detail": detail,
                    "locres_path": locres_status.get("locres_path")}


def main():
    if len(sys.argv) != 5:
        print(f"Usage: python {os.path.basename(__file__)} "
              "<palworld_pak> <lang> <cache_dir> <code1,code2,...|(empty=auto)>")
        sys.exit(2)
    pak_path, lang, cache_dir, codes_arg = sys.argv[1:5]
    codes = [c for c in codes_arg.split(",") if c]
    if not codes:
        # 空指定(装備選択ダイアログを初めて開くとき等、コード一覧をまだ
        # 知らない場合): 軽量なpak索引走査でカタログ自体をここで求める。
        try:
            codes = sorted(list_equipment_codes_from_pak(pak_path))
        except Exception as e:
            print(json.dumps({
                "ok": False, "source": "none",
                "detail": f"could not list equipment codes from pak "
                          f"({type(e).__name__}: {e}): {pak_path}",
                "locres_path": None, "names": {}, "codes": [],
            }, ensure_ascii=False))
            return
    names, status = resolve_display_names(pak_path, lang, codes, cache_dir)
    print(json.dumps({**status, "names": names, "codes": codes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
