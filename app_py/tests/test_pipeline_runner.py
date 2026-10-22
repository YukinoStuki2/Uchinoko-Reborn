# test_pipeline_runner.py -- WP-A2受入条件:
#   ①ヘッドレス関数がjob.jsonをDESIGN.md §2.1スキーマと1:1一致で生成
#   ②convert.ps1起動コマンド文字列が§2.1契約と一致
# (旧 --emit-wiring / tests\shipcheck\gui_wiring_check.py 相当のPython単体版。
#  DESIGN.md §5.2 WP-A2行。GUI起動を伴う確認はしない、単体テストのみ)
from __future__ import annotations

import json
import os
import re
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pytest  # noqa: E402

import pipeline_runner as pr  # noqa: E402
import settings  # noqa: E402

# gui_wiring_check.py (tests\shipcheck\gui_wiring_check.py) の
# REQUIRED_TOP_KEYS/REQUIRED_PATHS_KEYSと同じ集合(dev#114以降、engine_modeは
# 必須には含めない設計だが、書くこと自体は指揮者裁定により明示要求されている
# ため、本ファイルでは「必須キーは満たしつつ、engine_modeも追加で存在する」
# ことの両方を検査する)。
REQUIRED_TOP_KEYS = ["vrm_path", "avatar_name", "paths"]
REQUIRED_PATHS_KEYS = ["blender_exe", "vrm_addon_zip"]


# ---------------------------------------------------------------------------
# fixtures (tmp_path ベース、実Blender/実third_partyには依存しない)
# ---------------------------------------------------------------------------


def _make_app_root(tmp_path, with_blender=False, with_addon=False):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    if with_blender:
        blender_dir = app_root / "tools" / "blender-4.3.2-windows-x64"
        blender_dir.mkdir(parents=True)
        (blender_dir / "blender.exe").write_bytes(b"")
    if with_addon:
        (app_root / "third_party").mkdir()
        (app_root / "third_party" / "VRM_Addon_for_Blender-Extension-4_4_0.zip").write_bytes(b"")
    return str(app_root)


def _make_vrm(tmp_path, name="MyAvatar.vrm"):
    vrm = tmp_path / name
    vrm.write_bytes(b"")
    return str(vrm)


# ---------------------------------------------------------------------------
# sanitize_name (SanitizeName L.1734-1742)
# ---------------------------------------------------------------------------


def test_sanitize_name_keeps_only_ascii_alnum():
    assert pr.sanitize_name("My Avatar-02!") == "MyAvatar02"


def test_sanitize_name_unicode_input_falls_back_to_avatar():
    assert pr.sanitize_name("アバター") == "Avatar"


def test_sanitize_name_empty_falls_back_to_avatar():
    assert pr.sanitize_name("") == "Avatar"


# ---------------------------------------------------------------------------
# find_first / asset_sub_dir / find_blender
# ---------------------------------------------------------------------------


def test_asset_sub_dir_prefers_assets_subdir_when_present(tmp_path):
    app_root = tmp_path / "app_root"
    (app_root / "assets" / "tools").mkdir(parents=True)
    assert pr.asset_sub_dir(str(app_root), "tools") == str(app_root / "assets" / "tools")


def test_asset_sub_dir_falls_back_to_repo_root_when_assets_missing(tmp_path):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    assert pr.asset_sub_dir(str(app_root), "tools") == str(app_root / "tools")


def test_find_first_returns_none_for_missing_dir(tmp_path):
    assert pr.find_first(str(tmp_path / "nope"), "*.zip") is None


def test_find_first_returns_none_when_no_match(tmp_path):
    (tmp_path / "somefile.txt").write_text("x")
    assert pr.find_first(str(tmp_path), "*.zip") is None


def test_find_blender_found(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True)
    found = pr.find_blender(app_root)
    assert found.endswith(os.path.join("blender-4.3.2-windows-x64", "blender.exe"))
    assert os.path.isfile(found)


def _disable_hardcoded_blender_fallback(monkeypatch):
    """FindBlender() L.1840のハードコード開発機フォールバック
    (C:\\P\\Work\\PalMod\\tools\\blender-4.3.2-windows-x64)は、たまたま実機
    (この開発機)に実在すると「見つからない」ケースの検査が環境依存になり
    再現性が壊れる(実測: このマシンには実在した)。app_root配下だけを見る
    経路を検査したいテストのために、そのハードコードパスだけ「無い」ことに
    差し替える(app_root配下の実ファイル判定は素通しする)。"""
    hardcoded = os.path.normcase(
        os.path.abspath(r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe")
    )
    original_isfile = os.path.isfile

    def fake_isfile(path):
        if os.path.normcase(os.path.abspath(path)) == hardcoded:
            return False
        return original_isfile(path)

    monkeypatch.setattr(pr.os.path, "isfile", fake_isfile)


def test_find_blender_not_found_falls_back_to_bare_exe(tmp_path, monkeypatch):
    _disable_hardcoded_blender_fallback(monkeypatch)
    app_root = _make_app_root(tmp_path, with_blender=False)
    assert pr.find_blender(app_root) == "blender.exe"


# ---------------------------------------------------------------------------
# paks_dir_quiet (settings_paksdir.txtキャッシュのみ、ダイアログ無し)
# ---------------------------------------------------------------------------


def test_paks_dir_quiet_none_when_no_cache(tmp_path):
    app_root = _make_app_root(tmp_path)
    assert pr.paks_dir_quiet(app_root) is None


def test_paks_dir_quiet_uses_cached_settings_when_pak_present(tmp_path):
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()
    (paks_dir / pr.PAL_WINDOWS_PAK_NAME).write_bytes(b"")
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) == str(paks_dir)


def test_paks_dir_quiet_none_when_cached_dir_missing_pak(tmp_path):
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()  # Pal-Windows.pak無し
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) is None


def test_paks_dir_quiet_accepts_xbox_gamepass_pak_name(tmp_path):
    """dev#229続報: settings_paksdir.txtにXbox App版のPaksフォルダ
    (Pal-WinGDK.pakのみ)が保存されていても、以前は単一名決め打ちで
    「pak無し」扱いされていたが、いまは解決できる。"""
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "XboxPaks"
    paks_dir.mkdir()
    (paks_dir / "Pal-WinGDK.pak").write_bytes(b"xbox")
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) == str(paks_dir)


def test_paks_dir_quiet_none_when_only_unrelated_pak_present(tmp_path):
    """負の対照: 無関係な.pakが1つあるだけでは解決しない。"""
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()
    (paks_dir / "SomeOtherMod_P.pak").write_bytes(b"")
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) is None


# ---------------------------------------------------------------------------
# write_job: job.jsonスキーマ1:1一致 (DESIGN.md §2.1)
# ---------------------------------------------------------------------------


def test_write_job_top_level_keys_match_design_schema(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    work_root = str(tmp_path / "work")
    vrm = _make_vrm(tmp_path)

    job_json_path = pr.write_job(app_root, work_root, vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    # DESIGN.md §2.1のスキーマそのもの(§6-1裁定によりengine_modeを追加した版、
    # dev#560第③段でuniform_scaleを追加した版、dev#1230(2026-08-08)で
    # preflight_nonblockingを追加した版、dev#1572(2026-08-18、「揺れの度合い」
    # 4択の復元でsway_intensity/sway_enableを追加した版)——write_job()の
    # 既定sway_intensity="normal"により、無指定呼び出しでもこの2キーが常に
    # 書かれるようになった。旧`sway_enabled`(dev#1508 W2b由来のGUI内部専用
    # bool)は本WPでjob.jsonへの出力を廃止した)。
    expected_keys = {
        "vrm_path", "avatar_name", "shoulder_offset_deg", "merge_fingers",
        "unlit", "force_two_sided", "shadow_lift", "drop_bones",
        "license_confirmed", "engine_mode", "uniform_scale",
        "preflight_nonblocking", "paths",
        "sway_intensity", "sway_enable",
    }
    assert set(job.keys()) == expected_keys
    assert set(job["paths"].keys()) == {"blender_exe", "vrm_addon_zip", "palworld_pak"} \
        or set(job["paths"].keys()) == {"blender_exe", "vrm_addon_zip"}


def test_write_job_satisfies_gui_wiring_required_keys(tmp_path):
    """将来のC2(gui_wiring_check.py全面書換)がそのまま使えるよう、既存ゲートの
    必須キー集合(REQUIRED_TOP_KEYS/REQUIRED_PATHS_KEYS)を先取りで満たすことを
    確認する。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    work_root = str(tmp_path / "work")
    vrm = _make_vrm(tmp_path)

    job_json_path = pr.write_job(app_root, work_root, vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    for k in REQUIRED_TOP_KEYS:
        assert k in job, "top-level必須キー欠落: {}".format(k)
    assert isinstance(job["vrm_path"], str) and job["vrm_path"].strip()
    assert isinstance(job["avatar_name"], str) and job["avatar_name"].strip()
    assert isinstance(job["paths"], dict)
    for k in REQUIRED_PATHS_KEYS:
        assert k in job["paths"], "paths必須キー欠落: {}".format(k)
        assert isinstance(job["paths"][k], str) and job["paths"][k].strip()
    # 指揮者裁定: engine_modeは明示的に書く(§0参照)
    assert job["engine_mode"] == "noue"


def test_write_job_engine_mode_is_noue(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["engine_mode"] == pr.ENGINE_MODE == "noue"


def test_write_job_preflight_nonblocking_always_true(tmp_path):
    # dev#1230(2026-08-08オーナー裁定): GUI(ユーザーサイド)経由の変換は
    # 常にpreflight非ブロック。devtools\relgate.py等の開発側job.jsonは
    # write_job()を通らない(=このキー自体が無く、job.get既定Falseで
    # 従来どおりブロックする)ため、このテストの対象はGUI経路だけでよい。
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["preflight_nonblocking"] is True


def test_write_job_avatar_name_sanitized_from_filename(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path, name="My Cool Avatar!!.vrm")
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["avatar_name"] == "MyCoolAvatar"
    # jobDir = workRoot\<name> になっていること(WriteJob() L.1775)
    assert os.path.dirname(job_json_path) == os.path.join(str(tmp_path / "work"), "MyCoolAvatar")


def test_write_job_drop_bones_parsed_trimmed_and_filtered(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path),
        drop_bones_text=" Hair_L , , Hair_R ,,Tail ",
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["drop_bones"] == ["Hair_L", "Hair_R", "Tail"]


def test_write_job_drop_bones_empty_text_yields_empty_list(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), drop_bones_text=""
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["drop_bones"] == []


def test_write_job_shadow_lift_formula_matches_csharp():
    # WriteJob() L.1788-1789: shadow_lift = (100 - shadowBar.Value) / 100.0, 小数点以下3桁
    assert round((100 - 30) / 100.0, 3) == 0.7
    assert round((100 - 0) / 100.0, 3) == 1.0
    assert round((100 - 100) / 100.0, 3) == 0.0


def test_write_job_shadow_lift_value_wired(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), shadow_bar_value=30
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["shadow_lift"] == 0.7


# ---------------------------------------------------------------------------
# uniform_scale (dev#560 第③段: 身長スライダーGUI結線)
# ---------------------------------------------------------------------------


def test_write_job_uniform_scale_default_is_one(tmp_path):
    """負の対照(4b): スライダーに触れない既存ユーザーは既定1.0のまま。
    パイプライン側(apply_output_scale())は1.0を早期returnの完全no-opとして
    扱うため、既存ユーザーへの挙動影響はゼロ(dev#560第①段PR #1126)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["uniform_scale"] == 1.0
    # 既定値以外のフィールドは、uniform_scaleキーワード引数を渡さない
    # 呼び出しであっても他のテストと同じ既定値のまま(=このWPの追加が
    # 既存フィールドへ副作用を持たないことの確認)。
    assert job["shoulder_offset_deg"] == 0
    assert job["shadow_lift"] == 0.7


def test_write_job_uniform_scale_value_wired(tmp_path):
    """(4a): スライダー値(1.0以外)がjob.jsonへ写ること。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), uniform_scale=0.8
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["uniform_scale"] == 0.8


def test_write_job_uniform_scale_clamped_to_dev158_range(tmp_path):
    """(4c): 範囲外値(dev#158裁定0.5〜2.0)はクランプされる。UI(tk.Scale
    50〜200%)からは通常出ない値だが、write_job()自体にも多重防御として
    持たせてあるので直接呼び出しでも越境しないことを確認する。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path_low = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path, name="Low.vrm"),
        uniform_scale=0.1,
    )
    with open(job_json_path_low, encoding="utf-8") as f:
        assert json.load(f)["uniform_scale"] == 0.5

    job_json_path_high = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path, name="High.vrm"),
        uniform_scale=9.9,
    )
    with open(job_json_path_high, encoding="utf-8") as f:
        assert json.load(f)["uniform_scale"] == 2.0


# ---------------------------------------------------------------------------
# sway_intensity (dev#1572、2026-08-18裁定「かたさが配線されていない問題」
# 案C: v2.11方式の復元)。標準機能「揺れの度合い」の4択
# (none/soft/normal/hard)がjob["sway_intensity"]へ直接書かれ、
# job["sway_enable"](bool、アロケータのゲート)がsway_intensity!="none"の
# ときだけTrueで併記される。旧`sway_enabled`(dev#1508 W2b由来のGUI内部
# 専用bool)は本WPでjob.jsonへの出力を廃止した(下記テストで不在を確認)。
# ---------------------------------------------------------------------------


def test_write_job_sway_intensity_default_is_normal(tmp_path):
    """既定はSPEC復元前と同じ「ふつう」相当(sway_intensityを渡さない呼び
    出し)。job["sway_intensity"]=="normal"+job["sway_enable"]=Trueが書かれ、
    旧GUI内部専用キーjob["sway_enabled"]はもう書かれない。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["sway_intensity"] == "normal"
    assert job["sway_enable"] is True
    assert "sway_enabled" not in job


@pytest.mark.parametrize("intensity", ["soft", "normal", "hard"])
def test_write_job_sway_intensity_each_choice_is_written_verbatim(tmp_path, intensity):
    """4択のうちsoft/normal/hardは、選んだ値そのものがjob["sway_intensity"]へ
    書かれる(既存の一括刻印経路 pipeline\\py\\sway_abp_build.py
    hardness_key_for_intensity()がこの値をそのまま読む契約)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), sway_intensity=intensity)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["sway_intensity"] == intensity
    assert job["sway_enable"] is True


def test_write_job_sway_intensity_none_omits_keys(tmp_path):
    """負の対照: 「なし」(sway_intensity="none")のときはsway_intensity/
    sway_enableのどちらのキーも書かれない(=揺れ無し、旧「なし」と同じ
    挙動。ラボ憲章④「既定値のときは未実装状態と完全に同一」の踏襲)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), sway_intensity="none")
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "sway_intensity" not in job
    assert "sway_enable" not in job
    assert "sway_enabled" not in job


def test_write_job_hidden_compat_defaults_match_csharp_initial_fields(tmp_path):
    # DiveToPalworld.cs L.1042-1046: 「内部互換性のためにフィールドを初期化
    # (UIには表示しない)」既定値そのもの
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["shoulder_offset_deg"] == 0
    assert job["merge_fingers"] is False
    assert job["unlit"] is False
    assert job["force_two_sided"] is True
    assert job["license_confirmed"] is False


def test_write_job_paths_when_assets_found(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["blender_exe"].endswith("blender.exe")
    assert os.path.isfile(job["paths"]["blender_exe"])
    assert job["paths"]["vrm_addon_zip"].endswith(".zip")
    assert os.path.isfile(job["paths"]["vrm_addon_zip"])
    assert "palworld_pak" not in job["paths"]  # settings_paksdir.txt未設定


def test_write_job_paths_fallback_when_assets_missing(tmp_path, monkeypatch):
    _disable_hardcoded_blender_fallback(monkeypatch)
    app_root = _make_app_root(tmp_path, with_blender=False, with_addon=False)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["blender_exe"] == "blender.exe"
    assert job["paths"]["vrm_addon_zip"] == ""  # 見つからない場合はnull安全に空文字列


def test_write_job_palworld_pak_included_when_paksdir_cached(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()
    (paks_dir / pr.PAL_WINDOWS_PAK_NAME).write_bytes(b"")
    settings.save_paksdir(app_root, str(paks_dir))

    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["palworld_pak"] == str(paks_dir / pr.PAL_WINDOWS_PAK_NAME)


def test_write_job_palworld_pak_uses_xbox_gamepass_pak_name_when_cached(tmp_path):
    """dev#229続報: settings_paksdir.txtがXbox App版のPaksフォルダを指している
    とき、job.jsonのpaths.palworld_pakには実在するPal-WinGDK.pakのフルパスが
    書かれること(以前はPal-Windows.pak決め打ちで存在しないパスを書いていた)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    paks_dir = tmp_path / "XboxPaks"
    paks_dir.mkdir()
    (paks_dir / "Pal-WinGDK.pak").write_bytes(b"xbox")
    settings.save_paksdir(app_root, str(paks_dir))

    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["palworld_pak"] == str(paks_dir / "Pal-WinGDK.pak")
    assert os.path.isfile(job["paths"]["palworld_pak"])


def test_write_job_file_is_utf8_without_bom(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path, name="日本語アバター.vrm")
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm)
    raw = open(job_json_path, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")  # BOM無し
    text = raw.decode("utf-8")
    assert "日本語アバター.vrm" in text  # ensure_ascii=Falseで非ASCIIがそのまま出る


# ---------------------------------------------------------------------------
# read_job() (RestoreSettings L.1621-1628前段相当、dev#605/#616/#623)
# ---------------------------------------------------------------------------


def test_read_job_returns_none_when_file_missing(tmp_path):
    missing = str(tmp_path / "no_such_dir" / "job.json")
    assert pr.read_job(missing) is None


def test_read_job_returns_none_on_invalid_json(tmp_path):
    job_json = tmp_path / "job.json"
    job_json.write_text("{ not valid json", encoding="utf-8")
    assert pr.read_job(str(job_json)) is None


def test_read_job_round_trips_write_job_output(tmp_path):
    """write_job()が書いたjob.jsonをread_job()で読み戻すと、全キーが往復して
    一致すること(RestoreSettingsが自分の書いたWriteJob()の出力を読める、
    という最低限の契約)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), vrm,
        shoulder_offset_deg=5, merge_fingers=True, unlit=True,
        force_two_sided=False, shadow_bar_value=10,
        drop_bones_text="Bone_L, Bone_R", license_confirmed=True,
        uniform_scale=1.5,
    )
    data = pr.read_job(job_json_path)
    assert data is not None
    assert data["vrm_path"] == vrm
    assert data["shoulder_offset_deg"] == 5
    assert data["merge_fingers"] is True
    assert data["unlit"] is True
    assert data["force_two_sided"] is False
    assert data["drop_bones"] == ["Bone_L", "Bone_R"]
    assert data["license_confirmed"] is True
    assert data["shadow_lift"] == round((100 - 10) / 100.0, 3)
    assert data["uniform_scale"] == 1.5


# ---------------------------------------------------------------------------
# BuildConvertScriptPath / BuildConvertArgs / FindPwsh /起動コマンド契約
# (受入条件②: 起動コマンド文字列が§2.1の契約と一致)
# ---------------------------------------------------------------------------


def test_build_convert_script_path(tmp_path):
    app_root = str(tmp_path / "app_root")
    expected = os.path.join(app_root, "pipeline", "cli", "convert.ps1")
    assert pr.build_convert_script_path(app_root) == expected


def test_build_convert_args_no_flags():
    args = pr.build_convert_args(r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json")
    assert args == (
        '-NoProfile -ExecutionPolicy Bypass -File "C:\\app\\pipeline\\cli\\convert.ps1" '
        '-Job "C:\\work\\Avatar\\job.json"'
    )


def test_build_convert_args_preview_only():
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json", preview_only=True
    )
    assert args.endswith(" -PreviewOnly")
    assert "-MaterialsOnly" not in args


def test_build_convert_args_materials_only():
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json", materials_only=True
    )
    assert args.endswith(" -MaterialsOnly")
    assert "-PreviewOnly" not in args


def test_build_convert_args_both_flags_order():
    # BuildConvertArgs() L.1831-1833: previewOnlyが先、materialsOnlyが後
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json",
        preview_only=True, materials_only=True,
    )
    assert args.endswith(" -PreviewOnly -MaterialsOnly")


# gui_wiring_check.py の _ARGS_RE と同じ形の正規表現(§2.1契約の再検証)
_ARGS_RE = re.compile(r'^-NoProfile -ExecutionPolicy Bypass -File "([^"]+)" -Job "([^"]+)"')


def test_launch_command_matches_gui_wiring_contract_regex(tmp_path):
    app_root = str(tmp_path / "app_root")
    job_json = str(tmp_path / "work" / "Avatar" / "job.json")
    script = pr.build_convert_script_path(app_root)
    args = pr.build_convert_args(script, job_json)
    m = _ARGS_RE.match(args)
    assert m is not None
    assert m.group(1) == script
    assert m.group(2) == job_json


# dev#1242申し送りの共通化(本WP): pr.find_pwsh()はもはや独自実装を持たず、
# blender_setup.find_pwsh()(dev#1242で三点セット化済み)への薄い委譲になった
# (blender_setup.py側のdocstring・test_blender_setup.pyのfind_pwsh系試験が
# 正本)。ここでは「委譲が実際に効いていること」(=pipeline_runner経由でも
# 同じ根治が働くこと)だけを、赤→緑で直接検査する。


def test_find_pwsh_prefers_path_entry(tmp_path, monkeypatch):
    pwsh_dir = tmp_path / "pwshbin"
    pwsh_dir.mkdir()
    (pwsh_dir / "pwsh.exe").write_bytes(b"")
    monkeypatch.setenv("PATH", str(pwsh_dir))
    assert pr.find_pwsh() == str(pwsh_dir / "pwsh.exe")


def test_find_pwsh_falls_back_to_program_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    pf = tmp_path / "ProgramFiles"
    (pf / "PowerShell" / "7").mkdir(parents=True)
    (pf / "PowerShell" / "7" / "pwsh.exe").write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(pf))
    assert pr.find_pwsh() == str(pf / "PowerShell" / "7" / "pwsh.exe")


def test_find_pwsh_falls_back_to_powershell_exe(tmp_path, monkeypatch):
    # dev#1242で自動発見にSystem32絶対パス候補が追加されたため、真のbare名
    # フォールバックを検査するにはSystemRootも隔離する必要がある
    # (test_blender_setup._no_auto_discovery_pwsh_env と同じ隔離)。
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_pf_here"))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "no_such_system_root"))
    assert pr.find_pwsh() == "powershell.exe"


def test_find_pwsh_finds_system_powershell_by_absolute_path_even_with_broken_path_env(
    tmp_path, monkeypatch
):
    # 赤→緑の中核(本WP受入条件(1)): pipeline_runner.find_pwsh()経由でも
    # dev#1242の根治(<SystemRoot>\System32\WindowsPowerShell\v1.0\powershell.exe
    # への絶対パス発見、PATH非依存)が効くことを直接検査する。共通化前の旧
    # pipeline_runner.find_pwsh()はPATH+ProgramFilesしか見ておらず、この
    # ケースではbare名"powershell.exe"を返して壊れたPATH環境下で
    # WinError2を誘発していた(dev#1242実ユーザー報告と同型の欠陥)。
    monkeypatch.setenv("PATH", str(tmp_path / "no_such_path_dir"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_such_program_files"))
    # SystemRootは意図的に変更しない(本物の環境変数のまま、実在するWindows
    # 標準PowerShell 5.1を見つけられることを確認する)。

    result = pr.find_pwsh()
    assert result != "powershell.exe", (
        "PATHが壊れていてもbare名フォールバックへ落ちてはならない"
        "(絶対パス候補が実在するはず)"
    )
    assert os.path.isfile(result)
    assert "WindowsPowerShell" in result


def test_find_pwsh_delegates_to_blender_setup_find_pwsh(monkeypatch):
    # 共通化そのものの直接検査(負の対照込み): pipeline_runner.find_pwsh()が
    # blender_setup.find_pwsh()を実際に呼んでいること(=重複コードが復活して
    # いないこと)を、差し替えたスタブが呼ばれたかどうかで確認する。
    calls = []

    def fake_find_pwsh(app_root="", log=None):
        calls.append((app_root, log))
        return "STUBBED_PWSH.exe"

    monkeypatch.setattr(pr.blender_setup, "find_pwsh", fake_find_pwsh)
    log_lines = []
    result = pr.find_pwsh("C:\\dummy_app_root", log=log_lines.append)
    assert result == "STUBBED_PWSH.exe"
    assert calls == [("C:\\dummy_app_root", log_lines.append)]


# ---------------------------------------------------------------------------
# Unity輸出契約 (RunUnityExport L.2612-2682)
# ---------------------------------------------------------------------------


def test_build_unity_export_script_path(tmp_path):
    app_root = str(tmp_path / "app_root")
    expected = os.path.join(app_root, "pipeline", "cli", "export_from_unity.ps1")
    assert pr.build_unity_export_script_path(app_root) == expected


def test_resolve_unity_export_out_dir(tmp_path):
    work_root = str(tmp_path / "work")
    out_dir = pr.resolve_unity_export_out_dir(work_root, r"C:\proj\Assets\MyAvatar.prefab")
    assert out_dir == os.path.join(work_root, "MyAvatar_export")


def test_build_unity_export_args():
    args = pr.build_unity_export_args(
        r"C:\app\pipeline\cli\export_from_unity.ps1",
        r"C:\proj\Assets\MyAvatar.prefab",
        r"C:\work\MyAvatar_export",
    )
    assert args == (
        '-NoProfile -ExecutionPolicy Bypass -File "C:\\app\\pipeline\\cli\\export_from_unity.ps1" '
        '-Prefab "C:\\proj\\Assets\\MyAvatar.prefab" -Out "C:\\work\\MyAvatar_export"'
    )


def test_find_exported_fbx_returns_first_match(tmp_path):
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    (out_dir / "MyAvatar.fbx").write_bytes(b"")
    assert pr.find_exported_fbx(str(out_dir)) == str(out_dir / "MyAvatar.fbx")


def test_find_exported_fbx_none_when_missing(tmp_path):
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    assert pr.find_exported_fbx(str(out_dir)) is None


# ---------------------------------------------------------------------------
# busyBarモード切替 (dev#602: RunPipeline() L.2602 Continuous /
# RunUnityExport() L.2678 Marquee / OnUnityExportDone() L.2686 Continuous)
# ---------------------------------------------------------------------------


def test_initial_busy_bar_mode_unity_export_is_indeterminate():
    """RunUnityExport() L.2677-2679相当: 実進捗マーカーが無い工程は
    indeterminate(Marquee相当)から開始する。"""
    assert (
        pr.initial_busy_bar_mode(pr.PHASE_UNITY_EXPORT)
        == pr.BUSY_BAR_MODE_INDETERMINATE
    )


def test_initial_busy_bar_mode_pipeline_is_determinate():
    """RunPipeline() L.2602-2603相当: フル変換は開始直後からdeterminate
    (Continuous)。C#版はここでMarqueeにしない(##PROGRESS##が直後から
    流れ続けるため)。"""
    assert (
        pr.initial_busy_bar_mode(pr.PHASE_PIPELINE) == pr.BUSY_BAR_MODE_DETERMINATE
    )


def test_initial_busy_bar_mode_unknown_phase_falls_back_to_determinate():
    """負の対照: 未知のphase文字列(将来の呼び出しミス等)でも安全側の
    determinateへ倒れること(indeterminateに固定されたまま残るバグを防ぐ)。"""
    assert pr.initial_busy_bar_mode("something_else") == pr.BUSY_BAR_MODE_DETERMINATE


def test_busy_bar_mode_on_marker_is_always_determinate():
    """AppendLog()の##PROGRESS##到着時相当: マーカーが来た時点で実進捗が
    分かっているので、常にdeterminateへ戻す(OnUnityExportDone() L.2686と
    同じ「無条件でContinuousへ」という向き)。"""
    assert pr.busy_bar_mode_on_marker() == pr.BUSY_BAR_MODE_DETERMINATE


# ---------------------------------------------------------------------------
# Unity輸出フェーズの無音解消(dev#602追補、問い合わせZ5S945NP対応)
# ---------------------------------------------------------------------------


def test_should_emit_unity_export_heartbeat_false_before_interval():
    """まだ間隔未満なら発火しない(既定15秒、受入条件の30秒より短く安全側)。"""
    assert pr.should_emit_unity_export_heartbeat(0.0) is False
    assert pr.should_emit_unity_export_heartbeat(14.9) is False


def test_should_emit_unity_export_heartbeat_true_at_or_after_interval():
    """間隔ちょうど、またはそれ以上経過していれば発火する。"""
    assert pr.should_emit_unity_export_heartbeat(15.0) is True
    assert pr.should_emit_unity_export_heartbeat(999.0) is True


def test_should_emit_unity_export_heartbeat_respects_custom_interval():
    """interval_sec引数を明示指定した場合はそちらを使う(既定値への
    ハードコード依存がないことの確認)。"""
    assert pr.should_emit_unity_export_heartbeat(10.0, interval_sec=5.0) is True
    assert pr.should_emit_unity_export_heartbeat(3.0, interval_sec=5.0) is False


def test_format_elapsed_mmss_basic():
    assert pr.format_elapsed_mmss(0) == "00:00"
    assert pr.format_elapsed_mmss(5) == "00:05"
    assert pr.format_elapsed_mmss(65) == "01:05"
    assert pr.format_elapsed_mmss(3661) == "61:01"


def test_format_elapsed_mmss_truncates_fractional_seconds():
    """time.monotonic()差分は小数を含むが、表示は整数秒に切り捨てる。"""
    assert pr.format_elapsed_mmss(12.9) == "00:12"


def test_format_elapsed_mmss_negative_clamped_to_zero():
    """負の対照: 時計の巻き戻り等の異常値でも例外を出さず00:00に丸める
    (経過時間表示の補助機能が変換本体を巻き込んで死んではならない)。"""
    assert pr.format_elapsed_mmss(-5) == "00:00"


# ---------------------------------------------------------------------------
# 標準出力解析 (AppendLog L.2829-2883相当)
# ---------------------------------------------------------------------------


def test_strip_ansi_removes_color_codes():
    assert pr.strip_ansi("\x1b[31mred text\x1b[0m") == "red text"


def test_parse_progress_marker_basic():
    assert pr.parse_progress_marker("##PROGRESS## 42 Loading avatar") == (42, "Loading avatar")


def test_parse_progress_marker_clamps_to_0_100():
    assert pr.parse_progress_marker("##PROGRESS## 150 Overflow")[0] == 100
    assert pr.parse_progress_marker("##PROGRESS## -5 Underflow") is None  # 負数は\d+に非一致


def test_parse_progress_marker_none_when_not_matching():
    assert pr.parse_progress_marker("just a normal log line") is None


def test_parse_progress_marker_strips_ansi_first():
    line = "\x1b[32m##PROGRESS## 10 Preparing\x1b[0m"
    assert pr.parse_progress_marker(line) == (10, "Preparing")


def test_parse_avatar_warning_basic():
    assert pr.parse_avatar_warning("##AVATAR_WARNING## something looks off") == "something looks off"


def test_parse_avatar_warning_none_when_not_matching():
    assert pr.parse_avatar_warning("normal line") is None


# ---------------------------------------------------------------------------
# 進捗ラベル動的翻訳(ProgressLabelTemplates相当、A2担当分)
# ---------------------------------------------------------------------------


def test_translate_progress_label_dynamic_uses_fixed_dict_first():
    assert pr.translate_progress_label_dynamic("Loading avatar", lang="ja") == "アバターを読み込み中"


def test_translate_progress_label_dynamic_template_parallel_retarget():
    raw = "Retargeting skeleton + preview (parallel: Male, Female)"
    result = pr.translate_progress_label_dynamic(raw, lang="en")
    assert result == "Retargeting skeleton + preview (parallel: Male, Female)"
    result_ja = pr.translate_progress_label_dynamic(raw, lang="ja")
    assert result_ja == "スケルトン+プレビューをリターゲット中(並列: Male, Female)"


def test_translate_progress_label_dynamic_template_retarget_single():
    raw = "Retargeting skeleton (Male)"
    assert pr.translate_progress_label_dynamic(raw, lang="ja") == "スケルトンをリターゲット中(Male)"


def test_translate_progress_label_dynamic_template_preview_image():
    raw = "Generating preview image (Female)"
    assert pr.translate_progress_label_dynamic(raw, lang="zhCN") == "正在生成预览图(Female)"


def test_translate_progress_label_dynamic_unknown_label_passthrough():
    raw = "Some Brand New Stage Nobody Translated Yet"
    assert pr.translate_progress_label_dynamic(raw, lang="ja") == raw


def test_translate_progress_label_dynamic_empty_string():
    assert pr.translate_progress_label_dynamic("", lang="ja") == ""


# ---------------------------------------------------------------------------
# ProcessHandle: 実プロセス起動の非同期機構(convert.ps1やPalworldは起動しない、
# Pythonインタプリタ自身を子プロセスにしたごく軽量な単体試験)
# ---------------------------------------------------------------------------


def test_process_handle_captures_lines_and_exit_code():
    lines: list[str] = []
    exit_codes: list[int] = []
    script = 'import sys; print("hello"); print("world"); sys.exit(3)'
    handle = pr.ProcessHandle(
        sys.executable, '-c "{}"'.format(script.replace('"', '\\"')),
        on_line=lines.append, on_exit=exit_codes.append,
    )
    handle.start()
    import time

    deadline = time.time() + 10
    while time.time() < deadline and not exit_codes:
        handle.poll()
        time.sleep(0.05)
    handle.poll()

    assert lines == ["hello", "world"]
    assert exit_codes == [3]
    assert handle.exit_code == 3
    assert handle.is_running() is False


# ---------------------------------------------------------------------------
# load_previews: dev#1103(実報告TFVNM33V)。従来はMale固定パスしか探さない
# 実装だった。job.jsonのgenders絞り込み(convert_noue.py)でFemale専用生成
# された場合、Male側ファイルが存在せず「静かに何も表示しない」症状を招く
# 構造的弱点があった。GUIに性別選択ウィジェットは無いため、「選択性別」では
# なく「存在する方」(Male優先、無ければFemaleへフォールバック)を解決する。
# ---------------------------------------------------------------------------


def _write_preview_pair(job_dir: str, gender: str) -> tuple[str, str]:
    conv = os.path.join(job_dir, "converted")
    os.makedirs(conv, exist_ok=True)
    front = os.path.join(conv, f"preview_{gender}_stand.png")
    side = os.path.join(conv, f"preview_{gender}_stand_side.png")
    with open(front, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-front")
    with open(side, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-side")
    return front, side


def test_load_previews_male_present_negative_control(tmp_path):
    """負の対照: Maleのファイルが存在する従来どおりの構成では、Male経路の
    挙動が変わらないこと(修正の副作用でMale側が壊れていないことの確認)。"""
    job_dir = str(tmp_path / "job")
    front, side = _write_preview_pair(job_dir, "male")
    result = pr.load_previews(job_dir)
    assert result == {"front": front, "side": side}


def test_load_previews_female_only_selects_female_pair(tmp_path):
    """(a) job.jsonのgendersがFemaleのみ("genders": ["Female"])のような
    Female専用生成では、preview_male_stand.png が最初から存在しない。
    修正前はfront/sideとも常にNoneになり(Male固定パスしか見ないため)、
    実際に生成されたFemale側プレビューが一切GUIへ届かなかった。"""
    job_dir = str(tmp_path / "job")
    front, side = _write_preview_pair(job_dir, "female")
    result = pr.load_previews(job_dir)
    assert result == {"front": front, "side": side}


def test_load_previews_prefers_male_when_both_genders_present(tmp_path):
    """既定(genders未指定)のGUI標準フローでは両方生成される。frontとsideが
    異なる性別から混在して選ばれないことの確認(Male優先で一貫)。"""
    job_dir = str(tmp_path / "job")
    male_front, male_side = _write_preview_pair(job_dir, "male")
    _write_preview_pair(job_dir, "female")
    result = pr.load_previews(job_dir)
    assert result == {"front": male_front, "side": male_side}


def test_load_previews_neither_gender_present_returns_none(tmp_path):
    """(b) 変換未完了・生成失敗等でどちらの性別のファイルも存在しない場合は
    従来どおりfront/side共にNone(呼び出し元_apply_previewsのno-opログの
    入力となる)。"""
    job_dir = str(tmp_path / "job")
    os.makedirs(os.path.join(job_dir, "converted"), exist_ok=True)
    result = pr.load_previews(job_dir)
    assert result == {"front": None, "side": None}


# ---------------------------------------------------------------------------
# dev#1230(2026-08-08オーナー裁定): ユーザーサイドpreflight非ブロック化。
# resolve_preflight_result_path()/read_preflight_result()/
# is_preflight_fail_result() -- main_window.py側はこれらをそのまま呼ぶだけの
# tkinter配線しか持たない(ロジック本体はここで検査する)。
# ---------------------------------------------------------------------------


def test_resolve_preflight_result_path_is_under_build_dir(tmp_path):
    job_dir = str(tmp_path / "job")
    path = pr.resolve_preflight_result_path(job_dir)
    assert path == os.path.join(job_dir, "build", "preflight_result.json")


def test_read_preflight_result_missing_file_returns_none(tmp_path):
    job_dir = str(tmp_path / "job")
    assert pr.read_preflight_result(job_dir) is None


def test_read_preflight_result_reads_fail_status(tmp_path):
    job_dir = str(tmp_path / "job")
    os.makedirs(os.path.join(job_dir, "build"), exist_ok=True)
    with open(pr.resolve_preflight_result_path(job_dir), "w", encoding="utf-8") as f:
        json.dump(
            {"status": "FAIL", "returncode": 1, "failed_gates": ["G13 mismatch"]}, f
        )
    result = pr.read_preflight_result(job_dir)
    assert result == {"status": "FAIL", "returncode": 1, "failed_gates": ["G13 mismatch"]}


def test_read_preflight_result_corrupt_json_returns_none(tmp_path):
    # 負の対照: 壊れたJSON(書き込み途中でクラッシュした等)でも例外を
    # 外へ漏らさず、Noneとして安全側(=preflight FAIL扱いにしない)へ倒れる。
    job_dir = str(tmp_path / "job")
    os.makedirs(os.path.join(job_dir, "build"), exist_ok=True)
    with open(pr.resolve_preflight_result_path(job_dir), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert pr.read_preflight_result(job_dir) is None


def test_is_preflight_fail_result_true_only_for_fail_status():
    assert pr.is_preflight_fail_result({"status": "FAIL"}) is True
    assert pr.is_preflight_fail_result({"status": "PASS"}) is False
    assert pr.is_preflight_fail_result(None) is False
    assert pr.is_preflight_fail_result({}) is False


# ---------------------------------------------------------------------------
# dev#19/dev#1370(揺れもの、L1): job["springbones"]の配線
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(_APP_PY_DIR)
_VRM0_ALICIA = os.path.join(REPO_ROOT, "test", "vrm", "AliciaSolid_vrm-0.51.vrm")


def test_write_job_omits_springbones_key_when_vrm_has_no_spring_data(tmp_path):
    """既定不変(負の対照): springBoneデータが読めない/無いVRM(_make_vrmが
    書く空ファイル)では、job.jsonに"springbones"キー自体が現れない
    (ラボ憲章④パターン、test_write_job_top_level_keys_match_design_schemaの
    厳密一致アサーションが暗黙にこれも検査している。本テストは明示化)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "springbones" not in job


def test_write_job_prints_warning_when_vrm_springbone_parse_fails(tmp_path, capsys):
    """dev#1508 W1b: fail-open+ログ必須(タスク要件)。_make_vrmが書く空
    ファイルはGLBコンテナとして壊れている(catalog_from_vrm()がok=Falseを
    返す真の失敗ケース、上のomitsテストと同一入力)——変換は止めない
    (write_job()は例外を投げずjob.jsonを書き切る)が、警告が標準出力に
    出ること(fail-open+ログ必須の「ログ」側)を検査する。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "SpringBone" in captured.out


def test_write_job_skips_spring_parsing_for_prefab_input(tmp_path):
    """prefab入力(vrm_pathが.prefab)はこの時点でGLBコンテナではない
    (Unity輸出=Phase -1はconvert.ps1側で後から行われる)ため、
    vrm_spring_catalogを一切呼ばない——存在しない.prefabパスでも例外なく
    job.jsonが書ける(呼んでいたら存在しないファイルの読み取りで例外になる)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    prefab_path = str(tmp_path / "MyAvatar.prefab")  # 実在しない
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), prefab_path)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "springbones" not in job
    assert job["vrm_path"] == prefab_path


@pytest.mark.skipif(not os.path.isfile(_VRM0_ALICIA),
                     reason="test\\vrm\\AliciaSolid_vrm-0.51.vrm が無い環境"
                            "(gitignore対象、開発機のローカル資産)")
def test_write_job_wires_springbones_for_real_vrm0_sample(tmp_path):
    """実測(scratchpad/inspect_vrm.py、2026-08-16 dev#1508 W1b):
    AliciaSolid_vrm-0.51.vrmはboneGroups=3件(1boneGroup=1エントリへ再グループ化
    後の件数、DESIGN.md §2.2)、総chain数(揺れ骨のルート本数)は18のまま——
    write_job()経由でjob["springbones"]へ搬送される。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _VRM0_ALICIA)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "springbones" in job
    assert len(job["springbones"]) == 3
    assert sum(len(e["chains"]) for e in job["springbones"]) == 18
    assert all(e["source"] == "vrm0_spring" for e in job["springbones"])
    assert all(e["type"] == "springbone" for e in job["springbones"])
