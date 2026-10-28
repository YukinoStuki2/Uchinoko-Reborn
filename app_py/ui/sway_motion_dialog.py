"""Editor reusing the existing per-PhysBone chain settings."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import i18n
import sway_motion


def show_motion_dialog(parent, label, settings, on_save, *, enabled=True,
                       preserve_segments=False):
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("MotionTitle") + " — " + label)
    dlg.transient(parent)
    dlg.resizable(False, False)
    frame = ttk.Frame(dlg, padding=12)
    frame.pack(fill="both", expand=True)
    current = sway_motion.sanitize_motion_settings(settings)
    enabled_var = tk.BooleanVar(value=enabled)
    preserve_segments_var = tk.BooleanVar(value=preserve_segments is True)
    profiles = ("legacy", *sway_motion.PROFILES)
    labels = [i18n.S("MotionProfile" + profile.title()) for profile in profiles]
    ttk.Label(frame, text=i18n.S("MotionProfileLabel")).grid(row=0, column=0, sticky="w")
    profile = ttk.Combobox(frame, name="profile", values=labels, state="readonly", width=30)
    profile.current(profiles.index(current["profile"] if current else "legacy"))
    profile.grid(row=0, column=1, sticky="ew", pady=4)
    ttk.Label(frame, text=i18n.S("MotionAmount")).grid(row=1, column=0, sticky="w")
    amount = tk.Scale(frame, name="amount", from_=25, to=150, resolution=5,
                      orient="horizontal", length=270)
    amount.set(round((current or {}).get("amount", 1.0) * 100))
    amount.grid(row=1, column=1)
    controls = {}
    for index, (key, text_key, limits, resolution) in enumerate((
        ("damping", "MotionDamping", sway_motion.DAMPING_RANGE, 0.05),
        ("gravity_z", "MotionGravity", sway_motion.GRAVITY_RANGE, 5.0),
    ), start=2):
        enabled = tk.BooleanVar(value=key in (current or {}))
        check = ttk.Checkbutton(frame, text=i18n.S(text_key), variable=enabled)
        check.grid(row=index, column=0, sticky="w")
        scale = tk.Scale(frame, name=key, from_=limits[0], to=limits[1], resolution=resolution,
                         orient="horizontal", length=270)
        scale.set((current or {}).get(key, 0.4 if key == "damping" else 0.0))
        scale.grid(row=index, column=1)
        controls[key] = (enabled, scale)
    ttk.Label(frame, text=i18n.S("MotionEditorHint"), wraplength=500,
              justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
    preserve_check = ttk.Checkbutton(
        frame, name="preserve_segments", text=i18n.S("MotionPreserveSegments"),
        variable=preserve_segments_var)
    preserve_check.grid(row=5, column=0, columnspan=2, sticky="w")
    ttk.Label(frame, text=i18n.S("MotionPreserveSegmentsHint"), wraplength=500,
              justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(3, 8))

    def update_states(*_):
        active = profile.current() != 0
        amount.configure(state="normal" if active else "disabled")
        for enabled, scale in controls.values():
            scale.configure(state="normal" if active and enabled.get() else "disabled")
        preserve_check.configure(state="normal" if enabled_var.get() else "disabled")

    profile.bind("<<ComboboxSelected>>", update_states)
    for enabled, _scale in controls.values():
        enabled.trace_add("write", update_states)
    enabled_var.trace_add("write", update_states)
    update_states()

    def save():
        result = {"profile": profiles[profile.current()], "amount": amount.get() / 100.0}
        for key, (enabled, scale) in controls.items():
            if enabled.get():
                result[key] = scale.get()
        on_save(sway_motion.sanitize_motion_settings(result), enabled_var.get(),
                preserve_segments_var.get())
        dlg.destroy()

    def reset():
        profile.current(0)
        amount.set(100)
        preserve_segments_var.set(False)
        for enabled, _scale in controls.values():
            enabled.set(False)
        update_states()

    ttk.Checkbutton(frame, text=i18n.S("MotionEnabled"), variable=enabled_var).grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(0, 8))
    buttons = ttk.Frame(frame)
    buttons.grid(row=8, column=0, columnspan=2, sticky="ew")
    ttk.Button(buttons, text=i18n.S("MotionReset"), command=reset).pack(side="left")
    ttk.Button(buttons, text=i18n.S("BtnOk"), command=save).pack(side="right")
    ttk.Button(buttons, text=i18n.S("BtnCancel"), command=dlg.destroy).pack(side="right", padx=6)
    return dlg
