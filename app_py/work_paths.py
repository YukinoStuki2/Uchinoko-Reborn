"""Filesystem boundaries for model outputs and linked historical entries."""
from __future__ import annotations

import os
import stat


def shared_cache_root(work_root: str) -> str:
    """Match vp_core.shared_cache_root, including the launcher's shared override."""
    override = os.environ.get("D2P_SHARED_CACHE")
    return os.path.abspath(override) if override else os.path.join(os.path.abspath(work_root), "_shared_cache")


def is_directory_link(path: str) -> bool:
    """Recognize Windows junctions on embedded Python versions predating isjunction."""
    if os.path.islink(path):
        return True
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def require_local_output(path: str) -> None:
    if is_directory_link(path):
        raise ValueError(f"Linked historical output is read-only; choose a new model name or output directory: {path}")


def require_direct_job_child(work_root: str, job_dir: str) -> None:
    # Lexical comparison deliberately preserves a junction entry's identity.
    root = os.path.normcase(os.path.abspath(work_root))
    parent = os.path.normcase(os.path.dirname(os.path.abspath(job_dir)))
    if not work_root or root != parent:
        raise ValueError("The model job is not a direct child of the active output directory")
