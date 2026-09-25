"""Undo a rewrite: put quarantined files back where they were.

Rewrite-before-refuse turns `rm` into a move into `.hashimori-trash/<UTC stamp>/`,
keeping each file's relative path. `hashimori restore` lists those batches and
moves a batch back, never overwriting anything that exists again since.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

TRASH = ".hashimori-trash"


def batches(cwd: str | Path) -> list[dict]:
    root = Path(cwd) / TRASH
    out = []
    for b in sorted(root.glob("*")) if root.is_dir() else []:
        files = [p for p in b.rglob("*") if p.is_file()]
        out.append({"batch": b.name, "files": len(files),
                    "bytes": sum(p.stat().st_size for p in files),
                    "paths": sorted(str(p.relative_to(b)) for p in b.iterdir())})
    return out


def _put(src: Path, dst: Path, restored: list, conflicts: list) -> None:
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        restored.append(str(dst))
    elif src.is_dir() and dst.is_dir():
        for child in list(src.iterdir()):
            _put(child, dst / child.name, restored, conflicts)
    else:
        conflicts.append(str(dst))


def restore(cwd: str | Path, batch: str | None = None) -> dict:
    cwd = Path(cwd)
    found = batches(cwd)
    if not found:
        return {"restored": [], "conflicts": [], "batch": None, "message": "nothing in quarantine"}
    name = batch or found[-1]["batch"]
    src = cwd / TRASH / name
    if not src.is_dir():
        return {"restored": [], "conflicts": [], "batch": name, "message": "no such batch"}
    restored, conflicts = [], []
    for child in list(src.iterdir()):
        _put(child, cwd / child.name, restored, conflicts)
    # tidy empty directories left behind
    for d in sorted((p for p in src.rglob("*") if p.is_dir()), key=lambda p: len(str(p)), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        src.rmdir()
    except OSError:
        pass
    return {"restored": restored, "conflicts": conflicts, "batch": name,
            "message": f"restored {len(restored)} item(s)" + (f", {len(conflicts)} conflict(s) left in quarantine"
                                                             if conflicts else "")}
