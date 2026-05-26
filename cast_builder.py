# cast_builder.py
from __future__ import annotations

import os
import json
import base64
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# -----------------------------
# Utils
# -----------------------------
def _img_to_data_url(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    mime = f"image/{ext}"
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _stable_id(name: str, appearance: List[str]) -> str:
    """
    Stable ID based on name + appearance anchors. Prevents cast IDs from changing between runs.
    """
    seed = (name or "").strip().lower() + "||" + " ".join([a.strip().lower() for a in (appearance or [])])
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"char_{h}"


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object even if model returns extra text.
    Best effort: find first {...} block that parses.
    """
    text = (text or "").strip()
    if not text:
        return None

    # If already valid JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # Find JSON object blocks
    # This is a pragmatic approach: locate outermost braces.
    candidates = []
    starts = [m.start() for m in re.finditer(r"\{", text)]
    ends = [m.start() for m in re.finditer(r"\}", text)]
    if not starts or not ends:
        return None

    # Try widest-first: take substrings from each start to each end
    for s in starts:
        for e in reversed(ends):
            if e <= s:
                continue
            snippet = text[s : e + 1]
            if len(snippet) < 10:
                continue
            candidates.append(snippet)
        # try a few per start
        candidates = candidates[:8]

    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            continue

    return None


def _normalize_cast_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure payload has expected schema and normalize fields.
    """
    out = {
        "cast": [],
        "guidelines": payload.get("guidelines", {}) if isinstance(payload.get("guidelines", {}), dict) else {},
        "schema_version": 1,
    }

    raw_cast = payload.get("cast", [])
    if not isinstance(raw_cast, list):
        raw_cast = []

    for item in raw_cast:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip() or "Unknown"
        appearance = item.get("appearance", []) or []
        notes = item.get("notes", []) or []
        aliases = item.get("aliases", []) or []
        confidence = item.get("confidence", None)

        # Normalize list fields
        if isinstance(appearance, str):
            appearance = [appearance]
        if isinstance(notes, str):
            notes = [notes]
        if isinstance(aliases, str):
            aliases = [aliases]

        appearance = [str(x).strip() for x in appearance if str(x).strip()]
        notes = [str(x).strip() for x in notes if str(x).strip()]
        aliases = [str(x).strip() for x in aliases if str(x).strip()]

        # Add stable id if missing
        cid = str(item.get("id", "")).strip()
        if not cid or cid.lower().startswith("unknown"):
            cid = _stable_id(name, appearance)

        # Confidence (0..1) if present
        try:
            if confidence is None:
                confidence = 0.6
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except Exception:
            confidence = 0.6

        out["cast"].append(
            {
                "id": cid,
                "name": name,
                "appearance": appearance[:12],   # keep concise
                "notes": notes[:12],
                "aliases": aliases[:12],
                "confidence": confidence,
            }
        )

    # Deduplicate by id
    dedup = {}
    for c in out["cast"]:
        dedup[c["id"]] = c
    out["cast"] = list(dedup.values())

    return out


def _merge_cast(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge incoming cast entries into existing cast.json.
    - Prefer existing names if incoming is Unknown
    - Merge appearance/notes/aliases
    - Keep higher confidence
    """
    existing = existing or {}
    incoming = incoming or {}

    out = {
        "schema_version": max(int(existing.get("schema_version", 1)), int(incoming.get("schema_version", 1))),
        "guidelines": {**(existing.get("guidelines", {}) or {}), **(incoming.get("guidelines", {}) or {})},
        "cast": [],
    }

    ex_map = {c.get("id"): c for c in (existing.get("cast", []) or []) if isinstance(c, dict) and c.get("id")}
    in_map = {c.get("id"): c for c in (incoming.get("cast", []) or []) if isinstance(c, dict) and c.get("id")}

    all_ids = set(ex_map) | set(in_map)
    for cid in sorted(all_ids):
        e = ex_map.get(cid, {})
        n = in_map.get(cid, {})

        name_e = (e.get("name") or "").strip()
        name_n = (n.get("name") or "").strip()

        # Prefer non-Unknown name
        def is_unknown(x: str) -> bool:
            x = (x or "").strip().lower()
            return x in {"unknown", "unknown_1", "unknown_2"} or x.startswith("unknown")

        name = name_e
        if (not name_e) or is_unknown(name_e):
            name = name_n or name_e or "Unknown"
        elif name_n and not is_unknown(name_n) and name_n != name_e:
            # keep existing but add alias
            pass

        def merge_list(a, b, limit=14):
            a = a or []
            b = b or []
            if isinstance(a, str): a = [a]
            if isinstance(b, str): b = [b]
            seen = set()
            outl = []
            for x in [*a, *b]:
                xs = str(x).strip()
                if not xs: 
                    continue
                key = xs.lower()
                if key in seen:
                    continue
                seen.add(key)
                outl.append(xs)
                if len(outl) >= limit:
                    break
            return outl

        appearance = merge_list(e.get("appearance"), n.get("appearance"))
        notes = merge_list(e.get("notes"), n.get("notes"))
        aliases = merge_list(e.get("aliases"), n.get("aliases"))

        # If incoming had a good name but we kept existing, add it to aliases
        if name_n and name_n != name and not is_unknown(name_n):
            aliases = merge_list(aliases, [name_n])

        conf_e = float(e.get("confidence", 0.6) or 0.6)
        conf_n = float(n.get("confidence", 0.6) or 0.6)
        confidence = max(conf_e, conf_n)

        out["cast"].append(
            {
                "id": cid,
                "name": name,
                "appearance": appearance,
                "notes": notes,
                "aliases": aliases,
                "confidence": confidence,
            }
        )

    return out


# -----------------------------
# Main API
# -----------------------------
def build_cast(
    image_paths: List[Path],
    out_path: Path,
    model: str = "gpt-4.1-mini",
    merge_with_existing: bool = True,
) -> Dict[str, Any]:
    """
    Build cast.json from a small set of panels.
    - image_paths: 5-15 images with clear faces/introductions
    - out_path: path to cast.json
    - merge_with_existing: merge if cast.json already exists
    """
    if not image_paths:
        raise ValueError("image_paths is empty")

    # Filter valid images
    image_paths = [p for p in image_paths if p.exists() and p.suffix.lower() in IMG_EXTS]
    if not image_paths:
        raise ValueError("No valid image files provided")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    schema_instructions = """
Return STRICT JSON ONLY (no markdown, no commentary) with this schema:

{
  "cast": [
    {
      "id": "char_<stable>",
      "name": "KnownName or Unknown_1",
      "appearance": ["short hair", "blue coat", "scar on left cheek", "..."],
      "notes": ["role/relationship hints", "power/weapon hints", "..."],
      "aliases": ["nicknames", "alternate spellings"],
      "confidence": 0.0
    }
  ],
  "guidelines": {
    "naming_rules": ["Use consistent names", "If name unknown, use Unknown_1, Unknown_2..."],
    "matching_rules": ["Match by hair, clothes, face, scars, weapons", "Do not invent names"]
  }
}

Rules:
- If you cannot read a name: use Unknown_1, Unknown_2... and add strong appearance anchors.
- Keep appearance short and visual (hair color, outfit, scars, weapon, aura).
- confidence: 0.0 to 1.0 (how sure you are it’s the same recurring character).
- Do not include duplicate characters; merge if they’re the same person.
""".strip()

    content = [{"type": "input_text", "text": schema_instructions}]

    # Add images
    for p in image_paths[:20]:  # safety cap
        content.append({"type": "input_image", "image_url": _img_to_data_url(p)})

    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
    )

    raw = (resp.output_text or "").strip()
    parsed = _extract_json(raw)
    if not parsed:
        # Fallback: save raw so you can inspect
        fallback = {"cast": [], "guidelines": {}, "schema_version": 1, "raw": raw}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(fallback, indent=2, ensure_ascii=False), encoding="utf-8")
        return fallback

    incoming = _normalize_cast_payload(parsed)

    # Assign stable IDs if model didn't provide good ones
    for c in incoming.get("cast", []):
        if not c.get("id") or not str(c["id"]).startswith("char_"):
            c["id"] = _stable_id(c.get("name", ""), c.get("appearance", []))

    if merge_with_existing and out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        merged = _merge_cast(existing, incoming)
        out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        return merged

    out_path.write_text(json.dumps(incoming, indent=2, ensure_ascii=False), encoding="utf-8")
    return incoming


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True, help="Folder with panel images")
    p.add_argument("--out", required=True, help="Path to cast.json")
    p.add_argument("--model", default="gpt-4.1-mini")
    p.add_argument("--no-merge", action="store_true", help="Do not merge with existing cast.json")
    args = p.parse_args()

    in_dir = Path(args.in_dir)
    images = sorted([x for x in in_dir.iterdir() if x.suffix.lower() in IMG_EXTS])

    out = Path(args.out)
    build_cast(images, out, model=args.model, merge_with_existing=not args.no_merge)
    print(f"Saved cast -> {out}")