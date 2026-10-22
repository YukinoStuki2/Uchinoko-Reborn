# lab_window.py -- ラボ(実験的機能置き場)のUI基盤(dev#1186)。
#
# 正本: gh issue view 1186 --repo pandrabox/DiveToPalworld-dev
#   (2026-08-08オーナー裁定。ラボ憲章の正本はdev#277のオーナー2026-08-07
#   コメント: ①なくても普通の人は困らない ②あんまり試験しない雑な実装で
#   よい ③ちょっとアクセスしにくい場所に置く ④デフォルト値にしたときは
#   未実装状態と完全に同一)。
#
# 設計: メイン窓(main_window.py)には「ラボ」ボタン1個だけを追加し、実UIは
# すべてこのモジュールに閉じ込める(main_window.pyはopen_lab_window()を
# 呼ぶだけ)。ラボ窓はtkinterのgridジオメトリマネージャで1機能=1行、
# 列=[機能名/状態/設定...ボタン]。機能追加はLAB_FEATURESへLabFeature記述子
# 1個を足すだけで済む構造にしてある(dev#1186受入条件: 「機能追加=行を
# 1つ足すだけ」)。
#
# support_dialog.py と同じ分離方針(Context/State dataclassで呼び出し元と
# 疎結合にする代わり、ここでは呼び出し元=MainWindowインスタンスをそのまま
# `self`として各関数へ渡す軽量版。ラボ機能はmain_window.pyの既存ウィジェット
# (dropBonesBox等)を直接読み書きする前提のため、Context層を挟むより
# 素直で、レジストリ記述子の型もシンプルに保てる)。
#
# GUI起動不要のロジック層(dev#1186受入条件「警告表示の条件をロジック層の
# 単体テストで固定する」): any_feature_active()/reset_all_features()と
# 各機能のstatus_summary/reset_defaultは、`self.widgets["dropBonesBox"]`が
# `.get()/.delete()/.insert()`を持つ何か(実Entryでもテスト用フェイクでも)
# でありさえすれば動く。実tk.Toplevelの生成が要るのはopen_lab_window()/
# open_drop_bones_dialog()(ウィジェットを実際に置く関数)だけ。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pak_manager  # noqa: E402  (dev#165: 装備限定ダイアログのバニラpak解決に使う)
from ui import dt_flag_head_hide_dialog  # noqa: E402  (dev#1258: 「差替え中装備のみ頭OFF」ラボ機能)
from ui import drop_bones_dialog  # noqa: E402  (dev#1277: ボーンでメッシュ削除、選択式ダイアログ本体)
from ui import equipment_select_dialog  # noqa: E402  (dev#165: 装備限定ラボ機能)
from ui import headequip_select_dialog  # noqa: E402  (dev#277第1弾④: 頭装備切り替えラボ機能)
from ui import mesh_delete_dialog  # noqa: E402  (dev#1168前半: メッシュ削除ラボ機能)
from ui import multi_avatar_pak_dialog  # noqa: E402  (dev#1170 WP-3: マルチアバターPAK作成)
from ui import output_folder_dialog  # noqa: E402  (dev#1368: 出力先フォルダを開く)
from ui import shapekey_select_dialog  # noqa: E402  (dev#1168後半: シェイプキーラボ機能)
from ui import sway_style_dialog  # noqa: E402  (dev#19/#1418統合、wp_sway_panel、PR #1510: 「ゆれかた」統合パネル。旧sway_chain_dialog/lab_raw_sway_params_dialogをこのモジュールから置き換え、マイグレーションのためsway_styles_store.pyが内部でそれらを読む)
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

# MainWindowを型ヒントに使うとui.main_window <-> ui.lab_windowの循環import
# になる(main_window.pyがこのモジュールをimportする側)ため、`Any`で受ける。
MainWindowLike = Any


@dataclass(frozen=True)
class LabFeature:
    """ラボ機能1個ぶんの記述子(dev#1186仕様: id/i18n名称キー/状態サマリ
    関数/設定ダイアログを開く関数/既定値に戻す関数)。

    status_summary(self) -> Optional[str]: 既定(未変更)ならNone、
        変更されていれば短い要約文字列(例: "3本"、既にi18n.F等で組み立て
        済みの文言)を返す。
    open_dialog(self, parent, on_change) -> tk.Toplevel: 設定ダイアログを
        開く。値が変わるたびon_change()を呼ぶこと(ラボ窓の行・メイン窓の
        警告表示を再計算させるため)。
    reset_default(self) -> None: 既定値へ戻す(「全てのラボ機能を無効化」
        ボタンが全機能ぶんまとめて呼ぶ)。

    affects_conversion: dev#1170 WP-3で追加(既定True、既存5機能は無変更で
        済むようデフォルト値扱い)。Falseの機能はany_feature_active()の
        警告表示条件から除外される——「マルチアバターPAK作成」はメインパネル
        の通常変換(job.json)へ一切接続しない設計のため、非既定であっても
        メイン窓の『ラボ機能がONになっています』警告を出す理由が無い
        (オーナー確定仕様⑨「ラボ共通警告への合流は不要」)。行自体の状態列
        表示(status_summary)には影響しない——あくまで警告集約だけを外す。
    """

    feature_id: str
    name_key: str
    status_summary: Callable[[MainWindowLike], Optional[str]]
    open_dialog: Callable[[MainWindowLike, tk.Misc, Callable[[], None]], tk.Toplevel]
    reset_default: Callable[[MainWindowLike], None]
    affects_conversion: bool = True


# ---------------------------------------------------------------------------
# 機能①: ボーンでメッシュ削除(旧「こだわり設定」のdrop_bones、dev#1186で
# ラボへ移設。オーナー裁定「普通の人使わないからラボ落ちでいい」)。
#
# 設定値の保存先(widgets["dropBonesBox"]というEntry)・パイプラインへの
# 受け渡し(job設定のdrop_bonesキー、pipeline_runner.write_job()側)は
# main_window.py側で一切変えていない。ここではそのEntryを読み書きするだけ。
# ---------------------------------------------------------------------------


def _drop_bones_box(self: MainWindowLike):
    return self.widgets.get("dropBonesBox")


def drop_bones_status_summary(self: MainWindowLike) -> Optional[str]:
    box = _drop_bones_box(self)
    if box is None:
        return None
    names = [b.strip() for b in box.get().split(",") if b.strip()]
    if not names:
        return None
    return i18n.F("LabStatusDropBonesCountFormat", len(names))


def drop_bones_reset_default(self: MainWindowLike) -> None:
    box = _drop_bones_box(self)
    if box is not None:
        box.delete(0, tk.END)
    # dev#617: dropBonesBox.TextChanged相当。既存のFull Convertボタン鮮度
    # 再計算を、プログラム的なリセットでも(手打ちと同じく)必ず走らせる。
    on_changed = getattr(self, "_on_drop_bones_changed", None)
    if on_changed is not None:
        on_changed()


def open_drop_bones_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    """dev#1277: 旧実装(Entry1個+OKボタンのみのカンマ区切り手入力)を
    ui/drop_bones_dialog.py(チェックリスト選択式+検索+プレビュー更新
    ボタン、DESIGN.md 2.3/3節)へ切り出した。ここは薄いアダプタのみ——
    バッキングストア(widgets["dropBonesBox"]というEntry)の読み書き・
    鮮度判定の再計算(_on_drop_bones_changed)・avatar_path/work_rootの
    解決を、DropBonesContextのコールバックとして渡すだけ(mesh_delete_
    dialog.py/shapekey_select_dialog.pyのアダプタと同型)。データ経路
    (job設定のdrop_bonesキー、Blender側drop_bone_meshes()の完全一致)は
    一切変えていない。ウィンドウを×で閉じた場合は何も書き戻さない
    (=編集を破棄するキャンセル、旧実装と同じ挙動)。"""
    vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""

    def _get_text() -> str:
        box = _drop_bones_box(self)
        return box.get() if box is not None else ""

    def _set_text(text: str) -> None:
        box = _drop_bones_box(self)
        if box is not None:
            box.delete(0, tk.END)
            box.insert(0, text)

    def _on_changed() -> None:
        on_changed = getattr(self, "_on_drop_bones_changed", None)
        if on_changed is not None:
            on_changed()

    ctx = drop_bones_dialog.DropBonesContext(
        app_root=self.app_root, work_root=self.work_root, avatar_path=vrm_path,
        get_current_text=_get_text, set_current_text=_set_text,
        on_changed=_on_changed, append_log=getattr(self, "_log", lambda msg: None),
        # dev#1277(DESIGN.md 1.2節、WP1と同じ配線パターン): 保存直後に
        # 既存の再レンダ機構(こだわり設定パネルの旧「プレビュー更新」
        # ボタンと完全に同じ経路)を呼ぶ。フィールド名はWP1
        # (wp/dev1277-shapekey-preview-btn)のContextと合わせてある。
        trigger_preview=getattr(self, "_on_preview_only", None),
    )
    dlg = drop_bones_dialog.show_drop_bones_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


DROP_BONES_FEATURE = LabFeature(
    feature_id="drop_bones",
    name_key="LabFeatureDropBones",
    status_summary=drop_bones_status_summary,
    open_dialog=open_drop_bones_dialog,
    reset_default=drop_bones_reset_default,
)


# ---------------------------------------------------------------------------
# 機能②: 装備限定(dev#165、2026-08-08結線)。機能本体・状態永続化・
# ダイアログは ui/equipment_select_dialog.py にある(app_root文字列だけを
# 受け取る関数群+LAB_REGISTRY_DESCRIPTOR辞書。PR #1192本文の結線手順)。
# ここではその関数群を、このモジュールのLabFeature(self=MainWindowLikeを
# 受け取るdataclass)のインターフェースへつなぐ薄いアダプタだけを持つ
# (dictをそのままLAB_FEATURESへ入れると feature.status_summary(self) 等の
# 属性アクセス・呼び出し規約が合わないため、literal 1行では成立しない)。
# ---------------------------------------------------------------------------


def _equipment_filter_status_summary(self: MainWindowLike) -> Optional[str]:
    return equipment_select_dialog.state_summary(self.app_root)


def _equipment_filter_reset_default(self: MainWindowLike) -> None:
    equipment_select_dialog.reset(self.app_root)


def _resolve_palworld_pak(self: MainWindowLike) -> Optional[str]:
    """main_window.py既存箇所(例: _refresh_applied_pak_view)と同じ
    pak_manager.paks_dir_quiet()+resolve_pak_filename()の組み合わせで、
    装備名抽出(vp_equipment_names.py)に渡すバニラpakの実パスを解決する。
    未解決(Paksフォルダ未設定等)ならNone——呼び出し側の
    query_equipment_catalog()はNoneを「ok=False」として安全に処理する
    (三点セットのフォールバック、既存のvp_equipment_names.py docstring参照)。"""
    paks_dir = pak_manager.paks_dir_quiet(
        self.app_root, cache=getattr(self, "_paks_dir_cache", None)
    )
    if not paks_dir:
        return None
    filename = pak_manager.resolve_pak_filename(paks_dir)
    if not filename:
        return None
    return os.path.join(paks_dir, filename)


def _open_equipment_filter_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    ctx = equipment_select_dialog.EquipmentSelectContext(
        app_root=self.app_root,
        palworld_pak=_resolve_palworld_pak(self),
        lang=i18n.current_lang,
        append_log=getattr(self, "_log", lambda msg: None),
    )
    dlg = equipment_select_dialog.show_equipment_select_dialog(parent, ctx)
    # show_equipment_select_dialog()自体はon_changeコールバックを知らない
    # (drop_bonesダイアログと違いlab_window結線を前提に作られていない)ため、
    # OK/Cancel/×いずれの閉じ方でも一律<Destroy>でrefresh()相当を呼ぶ。
    # 状態の再読込に副作用は無いのでCancel/×でも無害(ラボ憲章②)。
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


EQUIPMENT_FILTER_FEATURE = LabFeature(
    feature_id=equipment_select_dialog.LAB_FEATURE_ID,
    name_key=equipment_select_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_equipment_filter_status_summary,
    open_dialog=_open_equipment_filter_dialog,
    reset_default=_equipment_filter_reset_default,
)


# ---------------------------------------------------------------------------
# 機能③: 頭装備切り替え(dev#277第1弾④、2026-08-08 オーナー裁定)。機能本体・
# 状態永続化・ダイアログは ui/headequip_select_dialog.py にある。ここでは
# 装備限定と同じ薄いアダプタだけを持つ(_resolve_palworld_pak()は既存の
# ものをそのまま再利用——UI取得の仕組み自体は装備限定と同じ)。
# ---------------------------------------------------------------------------


def _headequip_toggle_status_summary(self: MainWindowLike) -> Optional[str]:
    return headequip_select_dialog.state_summary(self.app_root)


def _headequip_toggle_reset_default(self: MainWindowLike) -> None:
    headequip_select_dialog.reset(self.app_root)


def _open_headequip_toggle_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    ctx = headequip_select_dialog.HeadEquipSelectContext(
        app_root=self.app_root,
        palworld_pak=_resolve_palworld_pak(self),
        lang=i18n.current_lang,
        append_log=getattr(self, "_log", lambda msg: None),
    )
    dlg = headequip_select_dialog.show_headequip_select_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


HEADEQUIP_TOGGLE_FEATURE = LabFeature(
    feature_id=headequip_select_dialog.LAB_FEATURE_ID,
    name_key=headequip_select_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_headequip_toggle_status_summary,
    open_dialog=_open_headequip_toggle_dialog,
    reset_default=_headequip_toggle_reset_default,
)


# ---------------------------------------------------------------------------
# 機能④: メッシュ削除(dev#1168前半、2026-08-09 オーナー指示)。機能本体・
# 状態永続化・ダイアログは ui/mesh_delete_dialog.py にある。入力アバターの
# メッシュ名一覧を対象にするため、他の装備系ラボ機能と異なりvrmBoxの中身
# (avatar_path)とwork_root(prefabのUnity輸出キャッシュ解決に使う)を渡す。
# ---------------------------------------------------------------------------


def _mesh_delete_status_summary(self: MainWindowLike) -> Optional[str]:
    avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    return mesh_delete_dialog.state_summary(self.app_root, avatar)


def _mesh_delete_reset_default(self: MainWindowLike) -> None:
    mesh_delete_dialog.reset(self.app_root)


def _open_mesh_delete_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    ctx = mesh_delete_dialog.MeshDeleteContext(
        app_root=self.app_root, work_root=self.work_root,
        avatar_path=vrm_path, append_log=getattr(self, "_log", lambda msg: None),
        trigger_preview=getattr(self, "_on_preview_only", None))
    dlg = mesh_delete_dialog.show_mesh_delete_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


MESH_DELETE_FEATURE = LabFeature(
    feature_id=mesh_delete_dialog.LAB_FEATURE_ID,
    name_key=mesh_delete_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_mesh_delete_status_summary,
    open_dialog=_open_mesh_delete_dialog,
    reset_default=_mesh_delete_reset_default,
)


# ---------------------------------------------------------------------------
# 機能⑤(dev#1258、2026-08-09オーナー裁定): 差替え中装備のみ頭OFF。
# ---------------------------------------------------------------------------


def _dt_flag_head_hide_status_summary(self: MainWindowLike) -> Optional[str]:
    return dt_flag_head_hide_dialog.state_summary(self.app_root)


def _dt_flag_head_hide_reset_default(self: MainWindowLike) -> None:
    dt_flag_head_hide_dialog.reset(self.app_root)


def _open_dt_flag_head_hide_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    ctx = dt_flag_head_hide_dialog.DtFlagHeadHideContext(
        app_root=self.app_root, append_log=getattr(self, "_log", lambda msg: None))
    dlg = dt_flag_head_hide_dialog.show_dt_flag_head_hide_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


DT_FLAG_HEAD_HIDE_FEATURE = LabFeature(
    feature_id=dt_flag_head_hide_dialog.LAB_FEATURE_ID,
    name_key=dt_flag_head_hide_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_dt_flag_head_hide_status_summary,
    open_dialog=_open_dt_flag_head_hide_dialog,
    reset_default=_dt_flag_head_hide_reset_default,
)


# ---------------------------------------------------------------------------
# 機能⑥(dev#1168後半、2026-08-09オーナー裁定): シェイプキー。
# ---------------------------------------------------------------------------


def _shapekey_status_summary(self: MainWindowLike) -> Optional[str]:
    avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    return shapekey_select_dialog.state_summary(self.app_root, avatar)


def _shapekey_reset_default(self: MainWindowLike) -> None:
    shapekey_select_dialog.reset(self.app_root)


def _open_shapekey_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    ctx = shapekey_select_dialog.ShapeKeySelectContext(
        app_root=self.app_root, work_root=self.work_root, avatar_path=avatar,
        append_log=getattr(self, "_log", lambda msg: None),
        trigger_preview=getattr(self, "_on_preview_only", None))
    dlg = shapekey_select_dialog.show_shapekey_select_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


SHAPEKEY_FEATURE = LabFeature(
    feature_id=shapekey_select_dialog.LAB_FEATURE_ID,
    name_key=shapekey_select_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_shapekey_status_summary,
    open_dialog=_open_shapekey_dialog,
    reset_default=_shapekey_reset_default,
)


# ---------------------------------------------------------------------------
# 機能⑦(dev#1170 WP-3、2026-08-09オーナー確定仕様): マルチアバターPAK作成。
# 機能本体・状態永続化(対応表)は multi_avatar_pak_store.py、ダイアログは
# ui/multi_avatar_pak_dialog.py にある。他の装備系ラボ機能(_resolve_
# palworld_pak()を既に使う機能②③)と同じ流儀でPalworldのバニラpakを解決し、
# 装備カタログ取得に使う。
#
# affects_conversion=False(オーナー確定仕様⑨): この機能はメインパネルの
# 通常変換(job.json)へ一切接続しない設計のため、メイン窓/ラボ窓共通の
# 「ラボ機能がONになっています」警告には合流させない。
# ---------------------------------------------------------------------------


def _multi_avatar_pak_status_summary(self: MainWindowLike) -> Optional[str]:
    return multi_avatar_pak_dialog.state_summary(self.app_root)


def _multi_avatar_pak_reset_default(self: MainWindowLike) -> None:
    multi_avatar_pak_dialog.reset(self.app_root)


def _open_multi_avatar_pak_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    ctx = multi_avatar_pak_dialog.MultiAvatarPakContext(
        app_root=self.app_root,
        work_root=self.work_root,
        palworld_pak=_resolve_palworld_pak(self),
        lang=i18n.current_lang,
        append_log=getattr(self, "_log", lambda msg: None),
        # dev#1328: 合成成功後の自動適用。既存の「Palworldに適用」ボタンと同じ
        # pak_manager系適用機構を再利用する_apply_pak_path_silent()(main_window.py)
        # をそのまま渡す(このダイアログ自身がpak_manager/messageboxを直接叩いて
        # 二重実装しないため)。
        apply_pak_path=getattr(self, "_apply_pak_path_silent", None),
        # dev#1352: 合成成功直後にメインGUIの作成済みMOD一覧(pakList)を更新する。
        # 通常変換完了時に既に使われている一覧更新の仕組み(_on_refresh_pak_list、
        # dev#601)をそのまま渡す(新規の更新機構は作らない)。
        refresh_pak_list=getattr(self, "_on_refresh_pak_list", None),
    )
    dlg = multi_avatar_pak_dialog.show_multi_avatar_pak_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


MULTI_AVATAR_PAK_FEATURE = LabFeature(
    feature_id=multi_avatar_pak_dialog.LAB_FEATURE_ID,
    name_key="LabFeatureMultiAvatarPak",
    status_summary=_multi_avatar_pak_status_summary,
    open_dialog=_open_multi_avatar_pak_dialog,
    reset_default=_multi_avatar_pak_reset_default,
    affects_conversion=False,
)


# ---------------------------------------------------------------------------
# 機能⑧(dev#19/#1418統合、2026-08-16、wp_sway_panel PR #1510): 「ゆれかた」
# 統合パネル。旧「揺れもの詳細設定」(sway_chain_dialog.py)+旧「生パラメータ
# 調整」(lab_raw_sway_params_dialog.py)を1つに統合。機能本体・状態永続化は
# app_py\sway_styles_store.py(旧2ストアを読んでマイグレーションする)、
# ダイアログは ui\sway_style_dialog.py にある。他のアバター依存ラボ機能
# (mesh_delete/shapekey/旧sway_chain)と同じくvrmBoxの中身(avatar_path)と
# work_root(prefabのUnity輸出キャッシュ解決に使う)を渡す。sample_modeは
# MainWindow起動時の`--sample`開発フラグ(製品には残さない、旧sway_chainの
# 流儀を踏襲)。
# ---------------------------------------------------------------------------


def _sway_style_status_summary(self: MainWindowLike) -> Optional[str]:
    avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    return sway_style_dialog.state_summary(self.app_root, avatar)


def _sway_style_reset_default(self: MainWindowLike) -> None:
    sway_style_dialog.reset(self.app_root)


def _open_sway_style_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
    ctx = sway_style_dialog.SwayStyleContext(
        app_root=self.app_root, work_root=self.work_root, avatar_path=vrm_path,
        sample_mode=bool(getattr(self, "_dev_sample_sway", False)),
        append_log=getattr(self, "_log", lambda msg: None))
    dlg = sway_style_dialog.show_sway_style_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


SWAY_STYLE_FEATURE = LabFeature(
    feature_id=sway_style_dialog.LAB_FEATURE_ID,
    name_key=sway_style_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_sway_style_status_summary,
    open_dialog=_open_sway_style_dialog,
    reset_default=_sway_style_reset_default,
)

# dev#1572(2026-08-18裁定「かたさが配線されていない問題」): 鎖ごとの
# 「ゆれかた」列・カスタムスタイル・生パラメータ編集UIは画面から隠蔽する
# (削除ではない——記述子・ダイアログ本体・ストアはすべて温存)。揺れの
# 強さは標準機能の4択(main_window.py swayIntensityBar、job.json
# `sway_intensity`)へ一本化した。
#
# **2026-08-19訂正(第2便PR#1584の過修正の是正、本WP)**: 上記の隠蔽を
# 「ラボ窓のLAB_FEATURESからSWAY_STYLE_FEATURE自体を除去する」形で実装した
# ところ、このパネル(PR #1510の統合パネル)が旧「揺れもの詳細設定」の
# チェインON/OFF+安全域スピンボックスも吸収済みだったため、安全域の
# 設定手段まで画面から消えてしまった(オーナー実測)。正しい隠蔽の粒度は
# 「ラボ窓の行(=パネルへの入口)は残し、パネル内の表示だけを『ゆれかた』
# 関連(スタイル一覧・鎖ごとの『ゆれかた』列・生パラメータ編集)に限定して
# 隠す」——本WPでSWAY_STYLE_FEATUREをLAB_FEATURESへ復帰させ、パネル側
# (ui\sway_style_dialog.py、_SWAY_STYLE_PICKER_VISIBLE定数)で「ゆれかた」
# 関連ウィジェットだけを非生成にする方式へ改めた。鎖一覧・安全域
# スピンボックス・OK/キャンセルは引き続き表示・編集できる。


# ---------------------------------------------------------------------------
# 機能⑨(dev#1368、2026-08-15オーナー裁定): 出力先フォルダを開く。機能本体は
# ui/output_folder_dialog.py にある。設定を持たないアクションのみのラボ機能
# のため、state_summaryは常にNone・resetはno-op(既に output_folder_dialog.py
# 側で実装済み)。パス解決はself.work_root(_resolve_work_root()の戻り値)を
# そのまま渡すだけ——他の装備系ラボ機能の_resolve_palworld_pak()のような
# 専用の解決ロジックは不要(既にMainWindowが保持する値を再利用するだけ)。
# affects_conversion=False: job設定に一切触れないため、マルチアバターPAK
# 作成(機能⑦)と同じ理由でラボ共通警告の集約対象から外す(実際には
# status_summaryが常にNoneなのでany_feature_active()には元々寄与しないが、
# 意図を明示するため揃える)。
# ---------------------------------------------------------------------------


def _output_folder_status_summary(self: MainWindowLike) -> Optional[str]:
    return output_folder_dialog.state_summary(self.app_root)


def _output_folder_reset_default(self: MainWindowLike) -> None:
    output_folder_dialog.reset(self.app_root)


def _open_output_folder_dialog(
    self: MainWindowLike, parent: tk.Misc, on_change: Callable[[], None]
) -> tk.Toplevel:
    ctx = output_folder_dialog.OutputFolderContext(
        work_root=self.work_root, append_log=getattr(self, "_log", lambda msg: None),
    )
    dlg = output_folder_dialog.show_output_folder_dialog(parent, ctx)
    dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
    return dlg


OUTPUT_FOLDER_FEATURE = LabFeature(
    feature_id=output_folder_dialog.LAB_FEATURE_ID,
    name_key=output_folder_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
    status_summary=_output_folder_status_summary,
    open_dialog=_open_output_folder_dialog,
    reset_default=_output_folder_reset_default,
    affects_conversion=False,
)


# 旧機能(dev#1418、2026-08-15「生パラメータ全解放パネル」)は上記
# SWAY_STYLE_FEATURE(機能⑧)に統合済み(wp_sway_panel PR #1510、
# 2026-08-16)。ダイアログ本体 ui\lab_raw_sway_params_dialog.py と
# ストア app_py\lab_raw_sway_params_store.py はマイグレーション元として
# sway_styles_store.py が引き続き読むため削除しない(結線のみここで除去)。


# 機能④(性別限定、dev#336)は非搭載。dev#336の2026-08-08オーナー裁定
# 「性別限定はラボ第1弾に搭載しない」(構造制約: DT行フラグが性別共通で
# 除外性別の首なしが必然)により、ラボ機能レジストリからは除去する
# (2026-08-08 dev#336裁定反映WP)。機能本体・状態永続化・ダイアログ
# (ui/gender_select_dialog.py、gender_filter_store.py)自体は将来のA2再
# 設計時の再利用に備えて残置——結線(このファイル・pipeline_runner.py)
# だけを外す。

# dev#1186初期ラインナップはdrop_bonesのみだったが、dev#165(装備限定)を
# 第2期の指揮者裁定・オーナーGOで結線する(2026-08-08、本ステージング
# ブランチでの作業)。機能追加=記述子1個の追加、という受入条件どおり。
# dev#277第1弾④(頭装備切り替え、2026-08-08)も同じ形で追加。
# dev#1572(2026-08-19、第2便PR#1584の過修正の是正、本WP): SWAY_STYLE_
# FEATURE(統合パネル、安全域スピンボックスの唯一の入口)はLAB_FEATURESへ
# 復帰させた(一度は隠蔽=このリストからの除去として実装されたが、それでは
# 安全域の設定手段まで消えてしまうため。上のSWAY_STYLE_FEATURE定義直前の
# コメント参照)。パネル内の「ゆれかた」関連ウィジェットの隠蔽は
# ui\sway_style_dialog.py側(_SWAY_STYLE_PICKER_VISIBLE定数)で行う。
LAB_FEATURES: list[LabFeature] = [
    DROP_BONES_FEATURE, EQUIPMENT_FILTER_FEATURE, HEADEQUIP_TOGGLE_FEATURE,
    MESH_DELETE_FEATURE, DT_FLAG_HEAD_HIDE_FEATURE, SHAPEKEY_FEATURE,
    MULTI_AVATAR_PAK_FEATURE, OUTPUT_FOLDER_FEATURE, SWAY_STYLE_FEATURE]


def _notify_lab_subwindow_opened(self: MainWindowLike) -> None:
    """dev#1572(ラボ窓ブロック、2026-08-18オーナー最終裁定): ラボ系
    サブウィンドウ(ラボ窓本体または機能別設定ダイアログ)を1つ新たに
    開いた直後に呼ぶ。`self`(実運用はMainWindow、テストはフェイクdouble)
    が`_on_lab_subwindow_opened`を持たない場合は静かに無視する
    (`main_window.py`と結線していない単体テストを壊さないための
    ガード、他のラボ機能アダプタの`getattr(self, "_log", ...)`と同じ流儀)。"""
    hook = getattr(self, "_on_lab_subwindow_opened", None)
    if hook is not None:
        hook()


def _notify_lab_subwindow_closed(self: MainWindowLike) -> None:
    """`_notify_lab_subwindow_opened()`と対になる、閉じたときの通知。"""
    hook = getattr(self, "_on_lab_subwindow_closed", None)
    if hook is not None:
        hook()


def any_feature_active(self: MainWindowLike) -> bool:
    """1つでもラボ機能が既定から変わっていればTrue(dev#1186の警告表示条件
    そのもの)。GUI非依存(widgets辞書の中身がEntry互換フェイクでも動く)。

    dev#1170 WP-3: affects_conversion=Falseの機能(マルチアバターPAK作成)は
    この集約から除外する(オーナー確定仕様⑨、LabFeature.affects_conversion
    のdocstring参照)。"""
    return any(
        feature.status_summary(self) is not None
        for feature in LAB_FEATURES
        if feature.affects_conversion
    )


def reset_all_features(self: MainWindowLike) -> None:
    """「全てのラボ機能を無効化」ボタンの本体。全機能のreset_defaultを
    順に呼ぶ(GUI非依存)。"""
    for feature in LAB_FEATURES:
        feature.reset_default(self)


def open_lab_window(self: MainWindowLike, parent: tk.Misc) -> tk.Toplevel:
    """ラボ窓を開く(dev#1186)。1機能=1行のgridレイアウト+下部に
    「全てのラボ機能を無効化」ボタン+警告文(補助表示、本命はメイン窓側の
    labWarningLabel、main_window.py._refresh_lab_warning参照)。

    シングルトンガード(dev#1279、2026-08-09オーナー報告「Labウィンドウが
    2つ開ける不具合」): 修正前はBtnLabを連打するたび無条件でtk.Toplevel()を
    新規生成しており、既存のラボ窓が開いたままかどうかを一切見ていなかった。
    直近生成したToplevelをself(MainWindowインスタンス。テストでは
    _FakeSelf)に`_lab_window_toplevel`として覚えておき、次回呼び出し時に
    `.winfo_exists()`でまだ生きていれば新規生成せず`lift()/focus_force()`で
    前面化するだけに留める。既に×(WM_DELETE_WINDOW)で閉じられていれば
    `winfo_exists()`がFalseを返すので、通常どおり新規に開き直す。"""
    existing = getattr(self, "_lab_window_toplevel", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return existing

    dlg = tk.Toplevel(parent)
    self._lab_window_toplevel = dlg
    dlg.title(i18n.S("LabWindowTitle"))
    dlg.resizable(False, False)
    dlg.transient(parent)
    i18n.register(dlg, "LabWindowTitle", lambda w, t: w.title(t))
    # dev#1572(ラボ窓ブロック): ラボ窓本体もサブウィンドウ1個としてカウント
    # する(ラボ窓自体は編集状態を持たないが、「ラボ系サブウィンドウが
    # 開いている間」の起点としてここから数える設計)。singleton guard
    # (既存ラボ窓へlift/focus_forceするだけの早期return分岐、この行より前)
    # は新規生成ではないため二重カウントしない。
    #
    # `event.widget is dlg`フィルタが必須: tkinterのbindtags既定仕様により、
    # Toplevel直下の子孫ウィジェット(Label/Button等)が破棄されるときも
    # そのDestroyイベントはToplevel自身のbindtag経由でこのハンドラへ届く
    # (実測固定: 子3個のToplevelをdestroy()すると本ハンドラは4回発火する
    # (子3+自身1)。上記test_drop_bones_dialog_ok_writes_back_and_calls_
    # on_change()のコメントの実測と同じ現象)。フィルタ無しではカウンタが
    # 大きく負へ振れる。
    _notify_lab_subwindow_opened(self)
    dlg.bind(
        "<Destroy>",
        lambda e: _notify_lab_subwindow_closed(self) if e.widget is dlg else None,
        add="+",
    )
    # 2026-08-08: オーナー指摘「ラボサブウィンドウが左上に出るのが使いにくい。
    # メインに重なるように」対応。サイズはgrid任せ(未指定)なので位置だけ足す。
    window_pos.apply_offset_position(dlg, parent)

    warning = tk.Label(
        dlg, text=i18n.S("LabWarningActive"), fg="#b00000", justify="left",
        wraplength=440, anchor="w",
    )
    warning.grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 8))
    i18n.register(warning, "LabWarningActive")

    header_feature = tk.Label(dlg, text=i18n.S("LabColFeatureName"))
    header_status = tk.Label(dlg, text=i18n.S("LabColStatus"))
    header_feature.grid(row=1, column=0, sticky="w", padx=12)
    header_status.grid(row=1, column=1, sticky="w", padx=12)
    i18n.register(header_feature, "LabColFeatureName")
    i18n.register(header_status, "LabColStatus")

    # dev#1343(2026-08-10 オーナー実機報告「マルチアバターウィンドウ開いてる
    # 状態で『全てのラボ機能無効化』をおすとリセットされない」): 全7ラボ機能
    # ダイアログ(drop_bones/equipment_filter/headequip_toggle/mesh_delete/
    # dt_flag_head_hide/shapekey/multi_avatar_pak)は共通して「開いた時点で
    # 永続ストアの現在値を1回だけメモリへスナップショットし、OK/プレビュー
    # 保存ボタンが押されたときにそのスナップショットをそのままディスクへ
    # 書き戻す(ディスクの再読込・マージは一切しない)」という実装になって
    # いる(横断調査の詳細はwork/NOTES.md参照)。「全てのラボ機能を無効化」で
    # ディスク側を既定値へ戻しても、開いたままのダイアログはそれに気づかず、
    # 後からOK/プレビュー保存を押すと古いスナップショットが書き戻されて
    # リセットが巻き戻る。
    #
    # 修正方針(構造で統一、個別対処はしない): 「全無効化」を押した時点で
    # 開いている全てのラボ機能ダイアログを先にdestroy()してからリセットする。
    # 全7ダイアログとも×閉じ(WM_DELETE_WINDOW=destroy)は「保存せず破棄」の
    # 契約が既に成立している(test_drop_bones_dialog_closing_without_ok_
    # discards_edits等で固定済み)ため、destroy()を呼ぶだけで安全にスナップ
    # ショットを捨てられる——7つのダイアログファイルには一切手を入れない
    # (dev#1341/#1342がmulti_avatar_pak_dialog.pyを並行編集中のため、衝突を
    # 構造的に避ける意味もある)。
    open_sub_dialogs: list[tk.Toplevel] = []

    rows: list[tuple[LabFeature, tk.Label]] = []
    grid_row = 2
    for feature in LAB_FEATURES:
        name_label = tk.Label(dlg, text=i18n.S(feature.name_key), anchor="w")
        name_label.grid(row=grid_row, column=0, sticky="w", padx=12, pady=4)
        i18n.register(name_label, feature.name_key)

        status_label = tk.Label(dlg, anchor="w")
        status_label.grid(row=grid_row, column=1, sticky="w", padx=12, pady=4)

        def _open(feature=feature) -> None:
            # 死んだ参照(既に×/OKで閉じたダイアログ)を追加前に間引く
            # (長時間ラボ窓を開いたままだと際限なく積もるのを防ぐ、軽い掃除)。
            open_sub_dialogs[:] = [d for d in open_sub_dialogs if d.winfo_exists()]
            sub_dlg = feature.open_dialog(self, dlg, refresh)
            open_sub_dialogs.append(sub_dlg)
            # dev#1572(ラボ窓ブロック): 個々の設定ダイアログもサブウィンドウ
            # 1個としてカウントする(既存の`on_change`(refresh)用<Destroy>
            # バインドとは別枠、add="+"で共存させる)。`event.widget is sub_dlg`
            # フィルタの必要性は上のopen_lab_window()側コメント参照(子孫
            # ウィジェットのDestroyでも同じハンドラが発火するtkinter仕様)。
            _notify_lab_subwindow_opened(self)
            sub_dlg.bind(
                "<Destroy>",
                lambda e, _d=sub_dlg: (
                    _notify_lab_subwindow_closed(self) if e.widget is _d else None
                ),
                add="+",
            )

        configure_btn = tk.Button(dlg, text=i18n.S("BtnLabConfigure"), command=_open)
        configure_btn.grid(row=grid_row, column=2, sticky="w", padx=12, pady=4)
        i18n.register(configure_btn, "BtnLabConfigure")

        rows.append((feature, status_label))
        grid_row += 1

    def refresh() -> None:
        for feature, status_label in rows:
            summary = feature.status_summary(self)
            if summary is None:
                status_label.config(text=i18n.S("LabStatusDisabled"), fg="#666666")
            else:
                status_label.config(
                    text=i18n.F("LabStatusActiveFormat", summary), fg="#b00000"
                )
        if any_feature_active(self):
            warning.grid()
        else:
            warning.grid_remove()
        on_refresh_main = getattr(self, "_refresh_lab_warning", None)
        if on_refresh_main is not None:
            on_refresh_main()
        # dev#1311: 作成済みMOD一覧(pakList)の再読込は、以前は
        # main_window.py._refresh_lab_warning() 側から行っていた(dev#1170
        # コミットcecbf70)。しかし_refresh_lab_warning()はpak一覧の行選択
        # (_on_pak_list_selected → _apply_restored_settings)からも毎回
        # 呼ばれるため、行をクリックした瞬間に一覧が作り直されて選択が
        # 即座に解除される回帰を招いた(オーナー実機報告「fusionが選択
        # できない」)。refresh()はラボ機能ダイアログの<Destroy>(=ダイアログを
        # 閉じたとき)・「全てのラボ機能を無効化」・言語切替からしか呼ばれず、
        # 行選択とは無縁の経路なので、ここへ一覧再読込を移すのが正しい
        # (ファイルシステム再走査は冪等・軽量なので他ラボ機能ダイアログ
        # close時にも一緒に走る副作用は許容、cecbf70時点の判断を踏襲)。
        # work_root/pakList未設定のフェイクself(test_lab_window_ui.py等の
        # _FakeSelf)を壊さないためのガードはmain_window.py側の旧実装と
        # 同じ流儀を踏襲する。
        on_refresh_pak_list = getattr(self, "_on_refresh_pak_list", None)
        if (
            on_refresh_pak_list is not None
            and hasattr(self, "work_root")
            and "pakList" in self.widgets
        ):
            on_refresh_pak_list()

    # 2026-08-08 第3弾(言語切替のobserver化): status_label群(LabStatusDisabled
    # /LabStatusActiveFormat)は機能の状態に応じて複数キーを動的に組み立てる
    # ため、i18n.register()の単一key前提には乗らない(dev#596のstatusLabel等
    # 既存の動的文言と同じ理由)。既存のi18n.register()の仕組みへ最小限だけ
    # 相乗りする形で、ダミーの再登録(text自体は使わずrefresh()を呼ぶだけ)を
    # 1件加える——apply_language()が呼ばれるたびにstatus_label群も追従する。
    def _status_refresh_on_language_change(_widget: tk.Misc, _text: str) -> None:
        refresh()

    i18n.register(dlg, "LabColStatus", _status_refresh_on_language_change)

    def _disable_all() -> None:
        # dev#1343: 個々のダイアログ側のOK/プレビュー保存が古いスナップ
        # ショットを書き戻してリセットを巻き戻す前に、開いている全ラボ
        # ダイアログを先に閉じる(上のopen_sub_dialogsコメント参照)。
        # dlg.destroy()自体は各ダイアログとも保存処理を持たない
        # (×閉じ=discardの既存契約)ため、ここで閉じても編集内容が
        # 意図せず保存されることはない。
        for sub_dlg in list(open_sub_dialogs):
            if sub_dlg.winfo_exists():
                sub_dlg.destroy()
        open_sub_dialogs.clear()
        reset_all_features(self)
        refresh()

    disable_all_btn = tk.Button(dlg, text=i18n.S("BtnLabDisableAll"), command=_disable_all)
    disable_all_btn.grid(
        row=grid_row, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 12)
    )
    i18n.register(disable_all_btn, "BtnLabDisableAll")

    refresh()
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg
