"""Runtime enforcement helpers for production governance.

This module provides lightweight guards that can be optionally imported by runtime
entrypoints to detect forbidden imports or runtime conditions and fail-fast.
The checks are intentionally simple and fast.
"""
from typing import Iterable
import sys


FORBIDDEN_TOP_LEVEL = (
    "research",
    "experimental",
    "recursive",
    "civilization",
    "memory",
    "future",
    "alignment",
    "autonomous",
    "self_modify",
    "notebooks",
    "training",
)


def check_imported_modules(forbidden: Iterable[str] = FORBIDDEN_TOP_LEVEL):
    """Raise RuntimeError if a forbidden top-level module is present in sys.modules."""
    found = []
    for name in list(sys.modules.keys()):
        top = name.split(".")[0]
        if top in forbidden:
            found.append(name)
    if found:
        raise RuntimeError(f"Forbidden runtime modules detected: {found}")


def enforce():
    """Convenience entrypoint used by runtime to perform enforcement checks."""
    check_imported_modules()
