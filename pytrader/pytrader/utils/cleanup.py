from __future__ import annotations

import os
import glob


def remove_globs(patterns: list[str]) -> list[str]:
    removed: list[str] = []
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed.append(path)
            except Exception:
                pass
    return removed


def run_default_cleanup() -> list[str]:
    patterns = [
        "logs/**/*.csv",
        "**/*.tmp",
        "**/*.cache",
        "**/__pycache__/**",
        "data/*.csv",
        "data/*.json",
    ]
    return remove_globs(patterns)


