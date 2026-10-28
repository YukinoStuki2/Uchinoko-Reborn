"""Exercise real Tk controls through persisted job and KP spec generation."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import i18n
import pipeline_runner
import sway_chain_override_store as store
from ui import sway_style_dialog as panel


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def button(widget, key):
    return next(w for w in walk(widget) if isinstance(w, (tk.Button, ttk.Button))
                and w.cget("text") == i18n.S(key))


def make_context(tmp_path):
    avatar = tmp_path / "avatar.prefab"
    avatar.write_text("", encoding="utf-8")
    sidecar = tmp_path / "avatar_export"
    sidecar.mkdir(exist_ok=True)
    data = {"format": "divetopalworld-physbones-1", "physbones": [
        {"anchor": "Hair", "pb_object_name": "Hair", "chains": [["Hair1", "Hair2"]],
         "params": {"pull": 0.5, "spring": 0.5, "limit_type": "None", "limit_rotation": [0, 0, 0]}},
        {"anchor": "Skirt", "pb_object_name": "Skirt", "chains": [["Skirt1", "Skirt2"]],
         "params": {"pull": 0.5, "spring": 0.5, "limit_type": "Hinge", "limit_rotation": [0, 0, 0]}},
    ]}
    (sidecar / "physbones.json").write_text(json.dumps(data), encoding="utf-8")
    return panel.SwayStyleContext(app_root=str(tmp_path), work_root=str(tmp_path), avatar_path=str(avatar))


def test_bulk_profile_only_updates_enabled_components_and_reaches_written_job(hidden_root, tmp_path):
    ctx = make_context(tmp_path)
    dlg = panel.show_sway_style_dialog(hidden_root, ctx)
    button(dlg, "MotionApplySource").invoke()
    button(dlg, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert len(entries) == 1
    assert entries[0]["bones"][0] == "Hair"
    assert entries[0]["motion"] == {"profile": "source", "amount": 1.0}
    output = pipeline_runner.write_job(ctx.app_root, ctx.work_root, ctx.avatar_path)
    job = json.loads(Path(output).read_text(encoding="utf-8"))
    assert job["sway_chain_overrides"] == entries
    assert panel.is_active(ctx.app_root, ctx.avatar_path)
    assert panel.state_summary(ctx.app_root, ctx.avatar_path)
    panel.reset(ctx.app_root)
    assert not store.load_config(ctx.app_root, ctx.avatar_path)


def test_individual_editor_enables_compatibility_and_persists_amount(hidden_root, tmp_path):
    ctx = make_context(tmp_path)
    dlg = panel.show_sway_style_dialog(hidden_root, ctx)
    motion_buttons = [w for w in walk(dlg) if isinstance(w, tk.Button)
                      and w.cget("text") == i18n.S("MotionConfigure")]
    motion_buttons[1].invoke()
    editor = next(w for w in dlg.winfo_children() if isinstance(w, tk.Toplevel))
    profile = next(w for w in walk(editor) if isinstance(w, ttk.Combobox))
    profile.current(2)
    profile.event_generate("<<ComboboxSelected>>")
    amount = next(w for w in walk(editor) if w.winfo_name() == "amount")
    amount.set(50)
    enabled = next(w for w in walk(editor) if isinstance(w, ttk.Checkbutton)
                   and w.cget("text") == i18n.S("MotionEnabled"))
    enabled.invoke()
    button(editor, "BtnOk").invoke()
    button(dlg, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert len(entries) == 1
    assert entries[0]["bones"][0] == "Skirt"
    assert entries[0]["enabled"] is True
    assert entries[0]["motion"] == {"profile": "calm", "amount": 0.5}
    reopened = panel.show_sway_style_dialog(hidden_root, ctx)
    button(reopened, "MotionConfigureActive").invoke()
    editor = next(w for w in reopened.winfo_children() if isinstance(w, tk.Toplevel))
    assert next(w for w in walk(editor) if w.winfo_name() == "amount").get() == 50
    button(editor, "MotionReset").invoke()
    button(editor, "BtnOk").invoke()
    button(reopened, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert "motion" not in entries[0]
    assert entries[0]["enabled"] is True


def open_component_editor(dlg, *, configured=False):
    button(dlg, "MotionConfigureActive" if configured else "MotionConfigure").invoke()
    return next(w for w in dlg.winfo_children() if isinstance(w, tk.Toplevel))


def segment_check(editor):
    return next(w for w in walk(editor) if w.winfo_name() == "preserve_segments")


def test_segment_option_defaults_off_without_changing_legacy_job(hidden_root, tmp_path):
    ctx = make_context(tmp_path)
    dlg = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(dlg)
    assert not segment_check(editor).instate(["selected"])
    assert next(w for w in walk(editor) if isinstance(w, ttk.Combobox)).current() == 0
    button(editor, "BtnOk").invoke()
    button(dlg, "BtnOk").invoke()
    assert store.load_config(ctx.app_root, ctx.avatar_path) == []
    job = json.loads(Path(pipeline_runner.write_job(ctx.app_root, ctx.work_root, ctx.avatar_path)).read_text(encoding="utf8"))
    assert not job.get("sway_chain_overrides")


def test_segment_option_survives_real_editor_save_restore_and_written_job(hidden_root, tmp_path):
    ctx = make_context(tmp_path)
    # A multi-branch PhysBone uses one component option but persists all source
    # chain keys, each retaining bones[0] as the planner's component anchor.
    sidecar = tmp_path / "avatar_export/physbones.json"
    data = json.loads(sidecar.read_text(encoding="utf8"))
    data["physbones"][0]["chains"].append(["HairLeft1", "HairLeft2"])
    sidecar.write_text(json.dumps(data), encoding="utf8")
    dlg = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(dlg)
    segment_check(editor).invoke()
    button(editor, "BtnOk").invoke()
    button(dlg, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert len(entries) == 2
    assert all(e["preserve_segments"] is True and e["bones"][0] == "Hair" for e in entries)
    assert all("motion" not in e for e in entries), "must also work with the legacy profile"
    job = json.loads(Path(pipeline_runner.write_job(ctx.app_root, ctx.work_root, ctx.avatar_path)).read_text(encoding="utf8"))
    assert job["sway_chain_overrides"] == entries

    reopened = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(reopened, configured=True)
    assert segment_check(editor).instate(["selected"])
    segment_check(editor).invoke()
    button(editor, "BtnCancel").invoke()
    # Cancelling the child dialog must not mutate the component's saved state.
    button(reopened, "MotionApplySource").invoke()
    button(reopened, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert all(e["preserve_segments"] is True and e["motion"]["profile"] == "source" for e in entries)

    reopened = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(reopened, configured=True)
    button(editor, "MotionReset").invoke()
    assert not segment_check(editor).instate(["selected"])
    button(editor, "BtnOk").invoke()
    button(reopened, "BtnOk").invoke()
    assert store.load_config(ctx.app_root, ctx.avatar_path) == []


def test_disabled_component_keeps_option_but_writes_enabled_false(hidden_root, tmp_path):
    ctx = make_context(tmp_path)
    dlg = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(dlg)
    profile = next(w for w in walk(editor) if isinstance(w, ttk.Combobox))
    profile.current(2)
    profile.event_generate("<<ComboboxSelected>>")
    segment_check(editor).invoke()
    enabled = next(w for w in walk(editor) if isinstance(w, ttk.Checkbutton)
                   and w.cget("text") == i18n.S("MotionEnabled"))
    enabled.invoke()
    assert segment_check(editor).instate(["disabled", "selected"])
    button(editor, "BtnOk").invoke()
    button(dlg, "BtnOk").invoke()
    entries = store.load_config(ctx.app_root, ctx.avatar_path)
    assert len(entries) == 1
    assert entries[0]["preserve_segments"] is True
    assert entries[0]["enabled"] is False
    assert entries[0]["motion"]["profile"] == "calm"
    job = json.loads(Path(pipeline_runner.write_job(ctx.app_root, ctx.work_root, ctx.avatar_path)).read_text(encoding="utf8"))
    assert job["sway_chain_overrides"] == entries
    reopened = panel.show_sway_style_dialog(hidden_root, ctx)
    editor = open_component_editor(reopened, configured=True)
    assert segment_check(editor).instate(["disabled", "selected"])
    button(editor, "BtnCancel").invoke()
    button(reopened, "BtnLabSwayChainReset").invoke()
    button(reopened, "BtnOk").invoke()
    assert store.load_config(ctx.app_root, ctx.avatar_path) == []


@pytest.mark.parametrize("value", [False, None, "true", "false", 1, {}, []])
def test_only_explicit_boolean_true_enables_segment_preservation(tmp_path, value):
    bones = ["Tail", "Tail1"]
    store.save_config(str(tmp_path), "avatar.prefab", [
        {"bones": bones, "enabled": True, "preserve_segments": value}],
        default_enabled_map={tuple(bones): True})
    assert store.load_config(str(tmp_path), "avatar.prefab") == []
