# project_store.py
from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# -----------------------------
# Sorting / utilities
# -----------------------------
_NUM_SPLIT = re.compile(r"(\d+)")


def natural_key(s: str) -> List[Any]:
    """Sort strings in human order: 2 < 10."""
    return [int(t) if t.isdigit() else t.lower() for t in _NUM_SPLIT.split(s)]


def safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def file_sha1(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Fast-ish hash for caching / change detection."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# -----------------------------
# Project paths
# -----------------------------
@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    panels: Path
    project_json: Path
    cast_json: Path
    narration_json: Path
    narration_txt: Path


def project_paths(base_dir: Path, project_name: str) -> ProjectPaths:
    root = base_dir / "panel_runs" / project_name
    return ProjectPaths(
        root=root,
        panels=root / "panels",
        project_json=root / "project.json",
        cast_json=root / "cast.json",
        narration_json=root / "narration.json",
        narration_txt=root / "narration.txt",
    )


def init_project(base_dir: Path, project_name: str) -> ProjectPaths:
    p = project_paths(base_dir, project_name)
    p.root.mkdir(parents=True, exist_ok=True)
    p.panels.mkdir(parents=True, exist_ok=True)

    if not p.project_json.exists():
        safe_write_json(
            p.project_json,
            {
                "project": project_name,
                "panels": [],  # list of {filename, order, status, meta}
                "settings": {
                    "language": "English",
                    "model": "gpt-4.1-mini",
                    "style": "Casual Gen-Z, cinematic pacing, no emojis, 1-3 short lines.",
                },
                "schema_version": 1,
            },
        )
    return p


# -----------------------------
# Project CRUD
# -----------------------------
def load_project(project_json: Path) -> Dict[str, Any]:
    return safe_read_json(project_json, default={"project": "unknown", "panels": [], "settings": {}, "schema_version": 1})


def save_project(project_json: Path, data: Dict[str, Any]) -> None:
    safe_write_json(project_json, data)


def scan_panels_folder(panels_dir: Path) -> List[Path]:
    files = [x for x in panels_dir.iterdir() if x.is_file() and x.suffix.lower() in IMG_EXTS]
    files.sort(key=lambda p: natural_key(p.name))
    return files


def _default_panel_record(filename: str, order: int) -> Dict[str, Any]:
    return {
        "filename": filename,
        "order": order,
        "status": "new",  # new|casted|done|missing
        "meta": {},
    }


def sync_project_panels(project_json: Path, panels_dir: Path, compute_hash: bool = False) -> Dict[str, Any]:
    """
    Sync project.json with the actual files present in panels_dir.
    - Adds new files
    - Keeps existing panel statuses
    - Marks removed files as 'missing' (does not delete records)
    - Reassigns order sequentially based on current ordering
    """
    data = load_project(project_json)
    existing_list = data.get("panels", [])
    existing: Dict[str, Dict[str, Any]] = {p.get("filename"): p for p in existing_list if p.get("filename")}

    disk_files = scan_panels_folder(panels_dir)
    disk_names = [p.name for p in disk_files]
    disk_set = set(disk_names)

    # Update or add panels that exist on disk
    merged: List[Dict[str, Any]] = []
    for i, fp in enumerate(disk_files, start=1):
        rec = existing.get(fp.name) or _default_panel_record(fp.name, i)

        # Preserve status unless it was missing
        if rec.get("status") == "missing":
            rec["status"] = "new"

        rec["order"] = rec.get("order", i)

        # Update minimal metadata (optional)
        meta = rec.get("meta", {}) or {}
        meta["size_bytes"] = fp.stat().st_size
        if compute_hash:
            meta["sha1"] = file_sha1(fp)
        rec["meta"] = meta

        merged.append(rec)

    # Mark old records whose files are gone as missing
    for fn, rec in existing.items():
        if fn not in disk_set:
            rec2 = dict(rec)
            rec2["status"] = "missing"
            merged.append(rec2)

    # Sort by order then filename, then renumber orders for the non-missing ones
    present = [p for p in merged if p.get("status") != "missing"]
    missing = [p for p in merged if p.get("status") == "missing"]

    present.sort(key=lambda x: (x.get("order", 999999), natural_key(x.get("filename", ""))))
    for i, p in enumerate(present, start=1):
        p["order"] = i

    # Keep missing entries at the end
    missing.sort(key=lambda x: natural_key(x.get("filename", "")))
    data["panels"] = present + missing

    save_project(project_json, data)
    return data


def set_panel_status(project_json: Path, filename: str, status: str) -> None:
    data = load_project(project_json)
    for p in data.get("panels", []):
        if p.get("filename") == filename:
            p["status"] = status
            break
    save_project(project_json, data)


def rename_orders(project_json: Path, new_order: List[str]) -> None:
    """
    Reorder panels according to the new_order list of filenames.
    Only affects panels that exist (non-missing).
    """
    data = load_project(project_json)
    panels = data.get("panels", [])

    # Index of desired order
    idx = {fn: i + 1 for i, fn in enumerate(new_order)}

    # Update orders for those filenames
    for p in panels:
        fn = p.get("filename")
        if fn in idx and p.get("status") != "missing":
            p["order"] = idx[fn]

    # Renumber sequentially based on order
    present = [p for p in panels if p.get("status") != "missing"]
    missing = [p for p in panels if p.get("status") == "missing"]

    present.sort(key=lambda x: (x.get("order", 999999), natural_key(x.get("filename", ""))))
    for i, p in enumerate(present, start=1):
        p["order"] = i

    data["panels"] = present + missing
    save_project(project_json, data)


def get_ordered_present_panels(project_json: Path) -> List[Dict[str, Any]]:
    """Convenience: returns only panels present on disk, ordered."""
    data = load_project(project_json)
    panels = [p for p in data.get("panels", []) if p.get("status") != "missing"]
    panels.sort(key=lambda x: x.get("order", 999999))
    return panels