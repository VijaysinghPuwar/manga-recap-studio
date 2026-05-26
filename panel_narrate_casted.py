# panel_narrate_casted.py
from __future__ import annotations

import os
import json
import base64
import re
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def _language_instructions(language: str) -> str:
    lang = (language or "English").strip()
    low = lang.lower()
    if low == "hindi":
        return (
            "OUTPUT LANGUAGE LOCK: Hindi only, written in Devanagari script (देवनागरी). "
            "Every narration line MUST be in Hindi. Do NOT write in English. "
            "If panel dialogue is in English, translate it to Hindi. "
            "You may keep proper character names (e.g., Naruto, Sasuke) as-is, but every other "
            "word must be Hindi in Devanagari. Never reply in English under any circumstance."
        )
    if low == "english":
        return "OUTPUT LANGUAGE LOCK: English only. Do not output any other language."
    return (
        f"OUTPUT LANGUAGE LOCK: {lang} only. Every narration line must be in {lang}. "
        f"Never reply in any other language."
    )


def _output_in_target_language(text: str, language: str) -> bool:
    if not text:
        return False
    low = (language or "").strip().lower()
    if low == "hindi":
        return bool(DEVANAGARI_RE.search(text))
    if low == "english":
        return not DEVANAGARI_RE.search(text)
    return True


# -----------------------------
# Image utilities
# -----------------------------
def _img_to_data_url(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    mime = f"image/{ext}"
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# -----------------------------
# JSON utilities (safe load/merge)
# -----------------------------
def _safe_load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cast(cast_json: Path) -> Dict[str, Any]:
    return _safe_load_json(cast_json, {"cast": [], "guidelines": {}, "schema_version": 1})


def load_narrations(narration_json: Path) -> Dict[str, Any]:
    return _safe_load_json(narration_json, {"model": "", "count": 0, "items": [], "schema_version": 1})


def narration_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Return {filename: item_dict}
    """
    out = {}
    for it in payload.get("items", []) or []:
        fn = it.get("filename")
        if fn:
            out[fn] = it
    return out


def write_narration_txt(
    out_dir: Path,
    ordered_filenames: List[str],
    items_by_file: Dict[str, Dict[str, Any]],
) -> None:
    lines = []
    for i, fn in enumerate(ordered_filenames, start=1):
        narr = (items_by_file.get(fn, {}) or {}).get("narration", "") or ""
        narr = narr.strip()
        if narr:
            lines.append(f"[Panel {i}] {narr}")
        else:
            lines.append(f"[Panel {i}]")
    (out_dir / "narration.txt").write_text("\n\n".join(lines), encoding="utf-8")


# -----------------------------
# Prompt builder
# -----------------------------
def build_prompt(cast: Dict[str, Any], style: str, language: str) -> str:
    """
    Prompt for a SINGLE panel narration.
    """
    cast_json = json.dumps(cast, ensure_ascii=False)

    return f"""
{_language_instructions(language)}

You are a manga/manhwa recap narrator.

Use this CAST to keep names consistent (do NOT invent new names):
{cast_json}

Task:
- Write narration for THIS SINGLE panel.
- Output ONLY narration text (no headings, no bullet points, no emojis).
- Do NOT say "in this panel/image".
- If dialogue exists, weave it naturally into narration — translated into the locked language.
- Keep story flow as if it's one continuous recap.

Name consistency rules:
- If you recognize a character, use their CAST name.
- If unclear, pick the closest Unknown_X based on appearance anchors in CAST.
- Never create a brand-new name that isn't in CAST.

Style (apply tone/pacing, but NEVER override the OUTPUT LANGUAGE LOCK above):
{style}

Length:
- 1 to 3 short lines max.

Return ONLY narration text in the locked language.
""".strip()


# -----------------------------
# Main function
# -----------------------------
def narrate_panels_with_cast(
    image_paths: List[Path],
    out_dir: Path,
    cast_json: Path,
    style: str,
    language: str,
    model: str = "gpt-4.1-mini",
    force: bool = False,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Generate narration for given images, using cast.json for consistency.

    - Incremental: updates narration.json after each panel.
    - Skips panels already narrated unless force=True.
    - progress_cb(current_index, total, filename) is called each step.
    """
    if not image_paths:
        raise ValueError("image_paths is empty")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    out_dir.mkdir(parents=True, exist_ok=True)

    cast = load_cast(cast_json)

    narration_json_path = out_dir / "narration.json"
    payload = load_narrations(narration_json_path)
    payload["model"] = model
    payload.setdefault("schema_version", 1)

    by_file = narration_map(payload)

    # Filter valid
    valid = [p for p in image_paths if p.exists() and p.suffix.lower() in IMG_EXTS]
    total = len(valid)
    if total == 0:
        raise ValueError("No valid image files found")

    prompt = build_prompt(cast, style, language)
    sys_instructions = (
        f"{_language_instructions(language)} "
        "You only output narration text. Never output English when another language is locked."
    )

    def _call(data_url: str, extra_user: str = "") -> str:
        user_text = prompt if not extra_user else f"{extra_user}\n\n{prompt}"
        resp = client.responses.create(
            model=model,
            instructions=sys_instructions,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        return (resp.output_text or "").strip()

    out_items = payload.get("items", []) or []
    # Use dict for easy update
    for idx, img_path in enumerate(valid, start=1):
        fn = img_path.name

        # skip if already narrated
        if not force and fn in by_file and (by_file[fn].get("narration") or "").strip():
            if progress_cb:
                progress_cb(idx, total, fn)
            continue

        if progress_cb:
            progress_cb(idx, total, fn)

        data_url = _img_to_data_url(img_path)
        narration = _call(data_url)
        if not _output_in_target_language(narration, language):
            retry_hint = (
                "STRICT RETRY: Your previous output was not in the locked language. "
                "Output Hindi in Devanagari only — no English words except proper names."
                if (language or "").strip().lower() == "hindi"
                else f"STRICT RETRY: Output ONLY in {language}."
            )
            narration = _call(data_url, retry_hint)

        # Update / insert item
        item = {
            "panel_number": idx,          # will be re-numbered in txt based on ordered list
            "filename": fn,
            "narration": narration,
        }
        if fn in by_file:
            # update existing in list
            for it in out_items:
                if it.get("filename") == fn:
                    it.update(item)
                    break
        else:
            out_items.append(item)

        # refresh map and save incrementally
        payload["items"] = out_items
        payload["count"] = len(out_items)
        by_file = narration_map(payload)
        _safe_write_json(narration_json_path, payload)

    # Final write txt in the order we were given
    ordered_filenames = [p.name for p in valid]
    write_narration_txt(out_dir, ordered_filenames, by_file)

    return payload