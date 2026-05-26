"""Project state persistence for the panel narration GUI.

Pure I/O layer — no Streamlit dependency. Safe to import from any context.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ---------- paths ----------

def get_paths(panel_runs_dir: Path, project: str) -> Dict[str, Path]:
    base = panel_runs_dir / project
    return {
        "root": base,
        "panels": base / "panels",
        "narr_json": base / "narration.json",
        "narr_txt": base / "narration.txt",
        "proj_json": base / "project.json",
    }


# ---------- json helpers ----------

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- panel files on disk ----------

def list_images(panels_dir: Path) -> List[str]:
    if not panels_dir.exists():
        return []
    files = [p.name for p in panels_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS]
    files.sort()
    return files


# ---------- project state ----------

def load_project_state(proj_json: Path, panels_dir: Path) -> Dict[str, Any]:
    """Load project.json, reconcile its panels list against the on-disk panels folder, save back."""
    data = load_json(
        proj_json,
        {"panels": [], "selected": None, "ui": {"auto_advance": True}},
    )
    disk = list_images(panels_dir)
    existing = {
        p["filename"]: p
        for p in data.get("panels", [])
        if isinstance(p, dict) and p.get("filename")
    }
    data["panels"] = [existing.get(fn, {"filename": fn, "status": "new"}) for fn in disk]
    if data.get("selected") not in disk:
        data["selected"] = disk[0] if disk else None
    if not isinstance(data.get("ui"), dict):
        data["ui"] = {}
    data["ui"].setdefault("auto_advance", True)
    write_json(proj_json, data)
    return data


def set_status(proj: Dict[str, Any], proj_json: Path, filename: str, status: str) -> Dict[str, Any]:
    for p in proj.get("panels", []):
        if p.get("filename") == filename:
            p["status"] = status
            break
    write_json(proj_json, proj)
    return proj


def progress_stats(panel_recs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts for the top-bar chips and progress line."""
    total = len(panel_recs)
    narrated = sum(1 for p in panel_recs if p.get("status") == "narrated")
    done = sum(1 for p in panel_recs if p.get("status") == "done")
    pct = int(round(((narrated + done) / total) * 100)) if total else 0
    return {"total": total, "narrated": narrated, "done": done, "pct": pct}


# ---------- narrations ----------

def load_narr_map(narr_json: Path) -> Dict[str, str]:
    data = load_json(narr_json, {"items": []})
    return {
        it["filename"]: (it.get("narration") or "")
        for it in (data.get("items") or [])
        if it.get("filename")
    }


def save_manual_narration(narr_json: Path, filename: str, narration: str) -> None:
    data = load_json(narr_json, {"model": "manual", "count": 0, "items": []})
    items = data.get("items") or []
    for it in items:
        if it.get("filename") == filename:
            it["narration"] = narration
            break
    else:
        items.append({"panel_number": 0, "filename": filename, "narration": narration})
    data["items"] = items
    data["count"] = len(items)
    write_json(narr_json, data)


def write_narration_txt(narr_txt: Path, ordered_files: List[str], narr_map: Dict[str, str]) -> None:
    lines = [
        f"[Panel {i}] {(narr_map.get(fn) or '').strip()}".strip()
        for i, fn in enumerate(ordered_files, start=1)
    ]
    narr_txt.write_text("\n\n".join(lines), encoding="utf-8")


# ---------- project listing ----------

def list_projects(panel_runs_dir: Path) -> List[Dict[str, Any]]:
    if not panel_runs_dir.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in panel_runs_dir.iterdir():
        if not p.is_dir():
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        panels_dir = p / "panels"
        count = (
            sum(1 for f in panels_dir.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXTS)
            if panels_dir.exists()
            else 0
        )
        out.append({"name": p.name, "panels": count, "mtime": mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def format_project_label(meta: Dict[str, Any]) -> str:
    mtime = meta.get("mtime") or 0
    try:
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        ts = "—"
    return f"{meta['name']}  ·  {meta['panels']} panels  ·  {ts}"
