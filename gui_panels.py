"""Streamlit GUI for the manga panel narrator.

Layout, top to bottom:
    Sidebar    project picker | narration settings | uploader
    Top bar    title | status chips | progress line
    Toolbar    Generate buttons | Re-analyze / Auto-advance toggles
    Main       scrollable panel list (left)  preview + narration editor (right)
    Footer     downloads | saved-path

Heavy lifting lives in two sibling modules:
    gui_storage  pure-Python project state I/O
    gui_styles   CSS + HTML render helpers
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import openai
import streamlit as st
from dotenv import load_dotenv

from panel_narrate import narrate_panels
import gui_storage as store
import gui_styles as ui

load_dotenv()

# ---------- constants ----------
BASE_DIR = Path.cwd()
PANEL_RUNS_DIR = BASE_DIR / "panel_runs"
NEW_PROJECT_SENTINEL = "__new_project__"
DEFAULT_PROJECT_NAME = "my_manga_project"
FILTER_OPTIONS = ["All", "New", "Narrated", "Done"]
FILTER_TO_STATUS = {"New": "new", "Narrated": "narrated", "Done": "done"}
STATUS_MARKERS = {"narrated": "●", "done": "✓"}


# ============================================================
# Page setup
# ============================================================

st.set_page_config(page_title="Manga Recap", page_icon="📖", layout="wide")
ui.inject_css()

if not os.getenv("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY not found. Add it to .env and restart Streamlit.")
    st.stop()

PANEL_RUNS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Sidebar
# ============================================================

def _project_picker() -> str:
    ui.render_label("Project")
    projects = store.list_projects(PANEL_RUNS_DIR)
    meta_by_name = {p["name"]: p for p in projects}

    if "project_name" not in st.session_state:
        st.session_state["project_name"] = projects[0]["name"] if projects else DEFAULT_PROJECT_NAME

    options = [p["name"] for p in projects] + [NEW_PROJECT_SENTINEL]
    current = st.session_state["project_name"]
    if current not in options:
        current = options[0] if options and options[0] != NEW_PROJECT_SENTINEL else NEW_PROJECT_SENTINEL

    def fmt(opt: str) -> str:
        if opt == NEW_PROJECT_SENTINEL:
            return "+ New project…"
        meta = meta_by_name.get(opt)
        return store.format_project_label(meta) if meta else opt

    chosen = st.selectbox(
        "Project",
        options=options,
        index=options.index(current),
        format_func=fmt,
        label_visibility="collapsed",
    )

    if chosen == NEW_PROJECT_SENTINEL:
        new_name = st.text_input(
            "New project name", value="", placeholder="e.g. ch 18", label_visibility="collapsed"
        )
        if (
            st.button("Create project", use_container_width=True, disabled=not new_name.strip())
            and new_name.strip()
        ):
            (PANEL_RUNS_DIR / new_name.strip() / "panels").mkdir(parents=True, exist_ok=True)
            st.session_state["project_name"] = new_name.strip()
            st.rerun()
        prev = st.session_state.get("project_name")
        return prev if prev not in (None, NEW_PROJECT_SENTINEL) else DEFAULT_PROJECT_NAME

    if chosen != st.session_state.get("project_name"):
        st.session_state["project_name"] = chosen
    st.caption(f"{len(projects)} project{'s' if len(projects) != 1 else ''} on disk")
    return chosen


def _narration_settings() -> Dict[str, str]:
    ui.render_label("Narration")
    return {
        "language": st.selectbox("Language", ["English", "Hindi"], index=0),
        "model": st.text_input("Model", value="gpt-4.1-mini"),
        "style": st.text_area(
            "Style",
            value="Casual Gen-Z, cinematic pacing, no emojis, 1-3 short lines, no 'in this panel'.",
            height=110,
        ),
    }


def _file_uploader():
    ui.render_label("Import Panels")
    return st.file_uploader(
        "Upload (JPG/PNG/WebP)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )


with st.sidebar:
    project_name = _project_picker()
    st.divider()
    settings = _narration_settings()
    st.divider()
    uploads = _file_uploader()


# ============================================================
# Project sync (after sidebar resolves the project)
# ============================================================

paths = store.get_paths(PANEL_RUNS_DIR, project_name)
paths["root"].mkdir(parents=True, exist_ok=True)
paths["panels"].mkdir(parents=True, exist_ok=True)

if uploads:
    for f in uploads:
        (paths["panels"] / f.name).write_bytes(f.getbuffer())
    st.toast(f"Imported {len(uploads)} panel(s)", icon="✓")

proj = store.load_project_state(paths["proj_json"], paths["panels"])
panel_recs = proj["panels"]
files = [p["filename"] for p in panel_recs]
status_by_file = {p["filename"]: p.get("status", "new") for p in panel_recs}


# ============================================================
# Top bar
# ============================================================

stats = store.progress_stats(panel_recs)
ui.render_top_bar(project_name, stats["total"], stats["narrated"], stats["done"], stats["pct"])

if not files:
    st.info("Upload images from the sidebar to begin.")
    st.stop()


# ============================================================
# Toolbar
# ============================================================

selected = proj.get("selected") or files[0]

tb = st.columns([1.2, 1.2, 0.4, 1.0, 1.0])
with tb[0]:
    gen_selected = st.button("Generate Selected", type="primary", use_container_width=True)
with tb[1]:
    gen_all = st.button("Generate All", use_container_width=True)
with tb[3]:
    reanalyze = st.toggle(
        "Re-analyze", value=False, help="Overwrite existing narrations during Generate All"
    )
with tb[4]:
    auto_advance = st.toggle(
        "Auto-advance",
        value=bool(proj.get("ui", {}).get("auto_advance", True)),
        help="Move to next panel after Save / Generate / Mark Done",
    )

proj["ui"]["auto_advance"] = bool(auto_advance)
store.write_json(paths["proj_json"], proj)


# ============================================================
# Filter helpers
# ============================================================

def _passes_filter(fn: str, choice: str) -> bool:
    return choice == "All" or status_by_file.get(fn, "new") == FILTER_TO_STATUS.get(choice, "")


def _step(filt: List[str], full: List[str], current: str, direction: str) -> str:
    """Next/prev filename: prefer the filtered list when current is in it; otherwise step in full."""
    if filt and current in filt:
        i = filt.index(current)
        return filt[min(i + 1, len(filt) - 1)] if direction == "next" else filt[max(i - 1, 0)]
    if filt:
        return filt[0]
    try:
        i = full.index(current)
    except ValueError:
        i = 0
    return full[min(i + 1, len(full) - 1)] if direction == "next" else full[max(i - 1, 0)]


# ============================================================
# Main layout
# ============================================================

left, right = st.columns([0.34, 0.66], gap="large")

with left:
    with st.container(border=True):
        ui.render_label("Panels")

        f_cols = st.columns([1.4, 1.0])
        with f_cols[0]:
            filter_choice = st.selectbox(
                "Filter", FILTER_OPTIONS, index=0, label_visibility="collapsed"
            )
        filtered_files = [fn for fn in files if _passes_filter(fn, filter_choice)]
        with f_cols[1]:
            ui.render_count_badge(len(filtered_files), len(files))

        displayed_selected = (
            selected if selected in filtered_files
            else (filtered_files[0] if filtered_files else selected)
        )

        if filtered_files:
            with st.container(height=440, border=False):
                for fn in filtered_files:
                    idx = files.index(fn) + 1
                    status = status_by_file.get(fn, "new")
                    marker = STATUS_MARKERS.get(status, "○")
                    label = f"{marker}  {idx:03d}   {fn}"
                    is_selected = (fn == displayed_selected)
                    if st.button(
                        label,
                        key=f"panel_btn_{fn}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    ) and fn != displayed_selected:
                        proj["selected"] = fn
                        store.write_json(paths["proj_json"], proj)
                        st.rerun()
        else:
            ui.render_filter_empty_state()

        nav = st.columns(2)
        nav_disabled = not filtered_files or displayed_selected not in filtered_files
        prev_disabled = nav_disabled or filtered_files.index(displayed_selected) == 0
        next_disabled = (
            nav_disabled or filtered_files.index(displayed_selected) == len(filtered_files) - 1
        )
        with nav[0]:
            prev_btn = st.button("← Prev", use_container_width=True, disabled=prev_disabled)
        with nav[1]:
            next_btn = st.button("Next →", use_container_width=True, disabled=next_disabled)

with right:
    with st.container(border=True):
        ui.render_label("Preview")
        ui.render_preview(
            paths["panels"] / displayed_selected,
            status=status_by_file.get(displayed_selected, "new"),
        )
        ui.render_filename_pill(displayed_selected)

    with st.container(border=True):
        ui.render_label("Narration")
        narr_map = store.load_narr_map(paths["narr_json"])
        narration_edit = st.text_area(
            "Narration editor",
            value=(narr_map.get(displayed_selected) or "").strip(),
            height=160,
            label_visibility="collapsed",
            placeholder="Generate narration, then edit here…",
        )
        b = st.columns([1, 1, 1])
        with b[0]:
            save_edit = st.button("Save Edit", use_container_width=True)
        with b[1]:
            regen = st.button("Regenerate", use_container_width=True)
        with b[2]:
            mark_done = st.button("Mark Done", type="primary", use_container_width=True)

selected = displayed_selected


# ============================================================
# Action handlers
# ============================================================

def _persist_selection(new_fn: str) -> None:
    proj["selected"] = new_fn
    store.write_json(paths["proj_json"], proj)


def _advance_if_enabled() -> None:
    if auto_advance and selected != files[-1]:
        _persist_selection(_step(filtered_files, files, selected, "next"))
        st.rerun()


if prev_btn:
    _persist_selection(_step(filtered_files, files, selected, "prev"))
    st.rerun()

if next_btn:
    _persist_selection(_step(filtered_files, files, selected, "next"))
    st.rerun()

if save_edit:
    store.save_manual_narration(paths["narr_json"], selected, narration_edit.strip())
    store.write_narration_txt(paths["narr_txt"], files, store.load_narr_map(paths["narr_json"]))
    if status_by_file.get(selected) == "new":
        proj = store.set_status(proj, paths["proj_json"], selected, "narrated")
    _advance_if_enabled()
    st.toast("Saved", icon="✓")

if mark_done:
    proj = store.set_status(proj, paths["proj_json"], selected, "done")
    _advance_if_enabled()
    st.toast("Marked done", icon="✓")

def _generate_safely(image_paths: List[Path]) -> bool:
    """Call narrate_panels and convert OpenAI errors into st.error banners. Returns success."""
    spinner_msg = (
        "Generating narration…"
        if len(image_paths) == 1
        else f"Generating narration for {len(image_paths)} panels…"
    )
    try:
        with st.spinner(spinner_msg):
            narrate_panels(
                image_paths=image_paths,
                out_dir=paths["root"],
                style=settings["style"],
                language=settings["language"],
                model=settings["model"],
            )
        return True
    except openai.AuthenticationError:
        st.error(
            "OpenAI rejected your API key (HTTP 401). Open `.env` and replace "
            "`OPENAI_API_KEY` with a valid key from "
            "https://platform.openai.com/api-keys, then click Generate again."
        )
    except openai.RateLimitError as e:
        st.error(f"OpenAI rate limit hit. Wait a moment and retry.\n\n{e}")
    except openai.APIConnectionError as e:
        st.error(f"Could not reach OpenAI. Check your internet connection.\n\n{e}")
    except openai.OpenAIError as e:
        st.error(f"OpenAI error: {e}")
    except Exception as e:  # noqa: BLE001 — last-resort UI guard
        st.error(f"Unexpected error during generation: {e}")
    return False


if regen or gen_selected:
    if _generate_safely([paths["panels"] / selected]):
        proj = store.set_status(proj, paths["proj_json"], selected, "narrated")
        store.write_narration_txt(paths["narr_txt"], files, store.load_narr_map(paths["narr_json"]))
        _advance_if_enabled()
        st.toast("Generated", icon="✓")
        st.rerun()

if gen_all:
    narr_map = store.load_narr_map(paths["narr_json"])
    targets = [
        paths["panels"] / fn
        for fn in files
        if reanalyze or not (narr_map.get(fn) or "").strip()
    ]
    if not targets:
        st.info("Nothing to generate (all panels already have narration).")
    elif _generate_safely(targets):
        target_names = {t.name for t in targets}
        for p in proj.get("panels", []):
            if p.get("filename") in target_names and p.get("status") != "done":
                p["status"] = "narrated"
        store.write_json(paths["proj_json"], proj)
        store.write_narration_txt(paths["narr_txt"], files, store.load_narr_map(paths["narr_json"]))
        st.toast("Generate All completed", icon="✓")
        st.rerun()


# ============================================================
# Footer
# ============================================================

st.divider()
foot = st.columns([1.2, 1.2, 3.6], gap="medium")
with foot[0]:
    if paths["narr_txt"].exists():
        st.download_button(
            "Download narration.txt",
            paths["narr_txt"].read_bytes(),
            file_name="narration.txt",
            use_container_width=True,
        )
with foot[1]:
    if paths["narr_json"].exists():
        st.download_button(
            "Download narration.json",
            paths["narr_json"].read_bytes(),
            file_name="narration.json",
            use_container_width=True,
        )
with foot[2]:
    ui.render_saved_path(str(paths["root"]))
