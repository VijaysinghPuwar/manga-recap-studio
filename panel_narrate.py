import os
import json
import base64
import re
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def _img_to_data_url(image_path: Path) -> str:
    # Supports .jpg/.jpeg/.png/.webp
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    mime = f"image/{ext}"
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _language_instructions(language: str) -> str:
    lang = (language or "English").strip()
    low = lang.lower()
    if low == "hindi":
        return (
            "OUTPUT LANGUAGE LOCK: Hindi only, written in Devanagari script (देवनागरी). "
            "Every narration line MUST be in Hindi. Do NOT write in English. "
            "If panel dialogue is in English, translate it to Hindi. "
            "You may keep proper character names (e.g., Naruto, Sasuke) as-is, but every other "
            "word must be Hindi in Devanagari. Never reply in English under any circumstance. "
            "If you are unsure what to say, still write Hindi in Devanagari."
        )
    if low == "english":
        return "OUTPUT LANGUAGE LOCK: English only. Do not output any other language."
    return (
        f"OUTPUT LANGUAGE LOCK: {lang} only. Every narration line must be in {lang}. "
        f"Never reply in any other language."
    )


def _output_in_target_language(text: str, language: str) -> bool:
    """Heuristic check that the model honored the language directive."""
    if not text:
        return False
    low = (language or "").strip().lower()
    if low == "hindi":
        return bool(DEVANAGARI_RE.search(text))
    if low == "english":
        # English should be Latin-script. Reject if any Devanagari leaked in.
        return not DEVANAGARI_RE.search(text)
    return True


def _build_user_prompt(style: str, language: str) -> str:
    return f"""
{_language_instructions(language)}

You are a manga/manhwa recap narrator.

Goal:
- Write narration for THIS SINGLE panel image.
- Output should be ONLY the narration line(s), no headings, no bullet points, no emojis.
- Keep it connected like a storyteller.
- Avoid describing "the panel" or "in this image" — just narrate what's happening.

Style (apply tone/pacing, but NEVER override the OUTPUT LANGUAGE LOCK above):
{style}

Rules:
- 1 to 3 short lines max.
- If the panel has dialogue, incorporate it naturally — translated into the locked language.
- If text is unreadable, infer from visuals and keep it simple.

Return ONLY narration text in the locked language.
""".strip()


def _generate_one(client: OpenAI, model: str, prompt: str, data_url: str, language: str) -> str:
    """Single-panel call with a system-level language lock and one validation retry."""
    sys = (
        f"{_language_instructions(language)} "
        "You only output narration text. Never output English when another language is locked."
    )

    def _call(extra_user: str = "") -> str:
        user_text = prompt if not extra_user else f"{extra_user}\n\n{prompt}"
        resp = client.responses.create(
            model=model,
            instructions=sys,
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

    narration = _call()
    if not _output_in_target_language(narration, language):
        retry_hint = (
            "STRICT RETRY: Your previous output was not in the locked language. "
            "Output Hindi in Devanagari only — no English words except proper names."
            if (language or "").strip().lower() == "hindi"
            else f"STRICT RETRY: Output ONLY in {language}."
        )
        narration = _call(retry_hint)
    return narration


def narrate_panels(
    image_paths: List[Path],
    out_dir: Path,
    style: str,
    language: str,
    model: str = "gpt-4.1-mini",
) -> Dict[str, Any]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_user_prompt(style, language)

    results = []
    for i, img_path in enumerate(image_paths, start=1):
        data_url = _img_to_data_url(img_path)
        narration = _generate_one(client, model, prompt, data_url, language)
        results.append(
            {
                "panel_number": i,
                "filename": img_path.name,
                "narration": narration,
            }
        )

    payload = {
        "model": model,
        "count": len(results),
        "items": results,
    }

    # Save JSON
    (out_dir / "narration.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save TXT (ready for TTS / YouTube script)
    txt = "\n\n".join([f"[Panel {x['panel_number']}] {x['narration']}".strip() for x in results])
    (out_dir / "narration.txt").write_text(txt, encoding="utf-8")

    return payload

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True, help="Folder with panel images")
    p.add_argument("--out-dir", required=True, help="Folder to write narration.json and narration.txt")
    p.add_argument("--style", default="Casual Gen-Z, energetic but clean, cinematic pacing.", help="Narration style")
    p.add_argument("--language", default="English", help="Narration language, e.g., English or Hindi")
    p.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model")
    args = p.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)

    imgs = sorted([p for p in in_dir.iterdir() if p.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]])
    if not imgs:
        raise SystemExit(f"No images found in {in_dir}")

    narrate_panels(imgs, out_dir, args.style, args.language, args.model)
    print(f"Done. Output -> {out_dir}")
