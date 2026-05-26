"""Static CSS and HTML rendering helpers for the panel narration GUI."""
from __future__ import annotations

import base64
import html as _html
from pathlib import Path

import streamlit as st

BASE_CSS = """
<style>
:root {
  --mr-accent: #3B82F6;
  --mr-accent-hi: #60A5FA;
  --mr-success: #22C55E;
  --mr-text-dim: #9AA0AB;
  --mr-border: #2A2E37;
}
.block-container { padding-top: 1.6rem; max-width: 1500px; }
[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"] { border-right: 1px solid var(--mr-border); }
h1, h2, h3, h4 { letter-spacing: -0.01em; }

.mr-label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--mr-text-dim); margin: 0 0 6px 0;
}
.mr-title {
  font-size: 26px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; margin: 0 0 8px 0;
}
.mr-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.mr-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 500;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--mr-border);
  color: var(--mr-text-dim);
}
.mr-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--mr-text-dim); }
.mr-dot.accent { background: var(--mr-accent); }
.mr-dot.success { background: var(--mr-success); }
.mr-progress { height: 3px; background: rgba(255,255,255,0.06); border-radius: 999px; overflow: hidden; }
.mr-progress > div { height: 100%; background: var(--mr-accent); transition: width 240ms ease; }
.mr-divider { height: 1px; background: var(--mr-border); margin: 14px 0 18px 0; }

.mr-preview {
  position: relative; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--mr-border); background: rgba(255,255,255,0.02);
  display: flex; align-items: center; justify-content: center;
}
.mr-preview img { max-width: 100%; max-height: 100%; object-fit: contain; }
.mr-badge {
  position: absolute; top: 10px; right: 10px;
  padding: 4px 9px; font-size: 10px; font-weight: 700;
  letter-spacing: 0.1em; border-radius: 6px;
  background: rgba(15,17,21,0.78); border: 1px solid var(--mr-border);
  color: var(--mr-text-dim);
}
.mr-badge.narrated { color: var(--mr-accent); border-color: rgba(59,130,246,0.4); }
.mr-badge.done { color: var(--mr-success); border-color: rgba(34,197,94,0.45); }
.mr-fname {
  display: inline-block; margin-top: 8px; padding: 2px 7px;
  background: rgba(255,255,255,0.05); border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px; color: var(--mr-text-dim);
}
.mr-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; padding: 7px 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--mr-border); border-radius: 6px;
  color: var(--mr-text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  direction: rtl; text-align: left;
}
.mr-path bdi { direction: ltr; unicode-bidi: bidi-override; }

/* Compact list-style buttons inside the panel scroll box (height=440). */
[data-testid="stVerticalBlock"][style*="height: 440px"] [data-testid="stButton"] > button,
[data-testid="stVerticalBlock"][style*="height:440px"] [data-testid="stButton"] > button {
  justify-content: flex-start;
  text-align: left;
  padding: 6px 12px;
  min-height: 32px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 400;
  border-radius: 6px;
}
[data-testid="stVerticalBlock"][style*="height: 440px"] [data-testid="stButton"],
[data-testid="stVerticalBlock"][style*="height:440px"] [data-testid="stButton"] {
  margin-bottom: 2px;
}
</style>
"""


def inject_css() -> None:
    st.html(BASE_CSS)


def render_top_bar(title: str, total: int, narrated: int, done: int, pct: int) -> None:
    safe_title = _html.escape((title or "—").upper())
    st.html(
        f'<div class="mr-title">{safe_title}</div>'
        f'<div class="mr-chips">'
        f'<span class="mr-chip"><span class="mr-dot"></span>{total} panels</span>'
        f'<span class="mr-chip"><span class="mr-dot accent"></span>{narrated} narrated</span>'
        f'<span class="mr-chip"><span class="mr-dot success"></span>{done} done</span>'
        f'</div>'
        f'<div class="mr-progress"><div style="width:{pct}%;"></div></div>'
        f'<div class="mr-divider"></div>'
    )


def render_preview(img_path: Path, status: str = "new", height_px: int = 380) -> None:
    ext = img_path.suffix.lower()
    mime = (
        "image/jpeg" if ext in (".jpg", ".jpeg")
        else "image/webp" if ext == ".webp"
        else "image/png"
    )
    b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
    badge_label = {"narrated": "NARRATED", "done": "DONE"}.get(status, "NEW")
    badge_class = {"narrated": "narrated", "done": "done"}.get(status, "new")
    st.html(
        f'<div class="mr-preview" style="height:{height_px}px;">'
        f'<img src="data:{mime};base64,{b64}" />'
        f'<span class="mr-badge {badge_class}">{badge_label}</span>'
        f'</div>'
    )


def render_filename_pill(filename: str) -> None:
    st.html(f'<div class="mr-fname">{_html.escape(filename)}</div>')


def render_saved_path(path: str) -> None:
    safe = _html.escape(path)
    st.html(
        f'<div class="mr-label" style="margin-bottom:4px;">Saved in</div>'
        f'<div class="mr-path" title="{safe}"><bdi>{safe}</bdi></div>'
    )


def render_label(text: str) -> None:
    st.html(f'<div class="mr-label">{_html.escape(text)}</div>')


def render_count_badge(visible: int, total: int) -> None:
    st.html(
        f'<div style="text-align:right; font-size:12px; color:var(--mr-text-dim); padding-top:8px;">'
        f'{visible} of {total}</div>'
    )


def render_filter_empty_state() -> None:
    st.html(
        '<div style="padding:16px 4px; color:var(--mr-text-dim); font-size:13px;">'
        'No panels match this filter.</div>'
    )
