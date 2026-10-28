"""Fixed output location editor; application owns validation and switching."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import i18n


class WorkRootDialog(tk.Toplevel):
    def __init__(self, parent, initial_path, apply_path):
        super().__init__(parent)
        self.title(i18n.S("TitleOutputDirectory"))
        self.transient(parent)
        self.resizable(True, False)
        self.minsize(720, 190)
        self._apply_path = apply_path
        self.path_var = tk.StringVar(self, value=initial_path)
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text=i18n.S("OutputDirectoryHelp"), wraplength=760).grid(
            row=0, column=0, columnspan=3, padx=16, pady=(16, 12), sticky="w")
        self.path_entry = ttk.Entry(self, textvariable=self.path_var, width=76)
        self.path_entry.grid(row=1, column=0, padx=(16, 8), sticky="ew")
        ttk.Button(self, text=i18n.S("BtnBrowse"), command=self._browse).grid(
            row=1, column=1, padx=(0, 8))
        ttk.Button(self, text=i18n.S("BtnOpenOutputDirectory"), command=self._open).grid(
            row=1, column=2, padx=(0, 16))
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, columnspan=3, pady=16, sticky="e", padx=16)
        self.save_button = ttk.Button(actions, text=i18n.S("BtnSaveOutputDirectory"), command=self._save)
        self.save_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text=i18n.S("BtnClose"), command=self.destroy).pack(side="left")
        self.path_entry.bind("<Return>", lambda _event: self._save())
        self.path_entry.focus_set()
        self.grab_set()

    def _browse(self):
        candidate = self.path_var.get().strip()
        chosen = filedialog.askdirectory(parent=self, title=i18n.S("TitleOutputDirectory"),
                                         initialdir=candidate if os.path.isdir(candidate) else None,
                                         mustexist=False)
        if chosen:
            self.path_var.set(chosen)

    def _open(self):
        path = self.path_var.get().strip()
        try:
            if not os.path.isdir(path):
                raise OSError(i18n.S("MsgOutputDirectoryMissing"))
            os.startfile(path)
        except OSError as exc:
            messagebox.showerror(i18n.S("TitleOutputDirectory"), str(exc), parent=self)

    def _save(self):
        if self._apply_path(self.path_var.get()):
            self.destroy()
