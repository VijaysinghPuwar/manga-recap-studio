# Manga Recap App

## Quick Start

This app runs on Windows and macOS with one launcher.

### Windows

1. Install Python 3.10 or newer from https://www.python.org/downloads/.
2. Download this repository and unzip it.
3. Double-click `run_windows.bat`.
4. On first run, open the generated `.env` file and set `OPENAI_API_KEY`.
5. Run `run_windows.bat` again.

### macOS

1. Install Python 3.10 or newer from https://www.python.org/downloads/.
2. Download this repository and unzip it.
3. Double-click `run_mac.command`.
4. On first run, open the generated `.env` file and set `OPENAI_API_KEY`.
5. Run `run_mac.command` again.

If macOS blocks the launcher, open Terminal in this folder and run:

```bash
chmod +x run_mac.command run_mac.sh
./run_mac.command
```

The launcher creates a local `.venv`, installs dependencies, and starts the Streamlit app at `http://localhost:8501`.

## What The App Does

- Upload manga/manhwa panel images.
- Generate narration with OpenAI vision models.
- Edit, save, and mark panels complete.
- Download `narration.json` and `narration.txt` for video or TTS workflows.

## Environment

Create a `.env` file in the project root. The launchers do this automatically from `.env.example` when `.env` does not exist.

```env
OPENAI_API_KEY=PASTE_YOUR_OPENAI_API_KEY_HERE
ELEVENLABS_API_KEY=PASTE_YOUR_ELEVENLABS_KEY_HERE
```

`OPENAI_API_KEY` is required for narration generation. `ELEVENLABS_API_KEY` is only needed for the optional video recap pipeline.

## Manual Run

If you prefer Terminal:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run gui_panels.py
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run gui_panels.py
```

## Optional Full PDF/Video Pipeline

The original batch pipeline in `app.py` can process PDFs, extract panels, generate summaries, create narration, and render a recap video. It has heavier dependencies. Install them with:

```bash
python -m pip install -r requirements-full.txt
```

Expected PDF layout:

```text
naruto/
  chapter-reference.pdf
  profile-reference.pdf
  v10/
    v10.pdf
```

Run:

```bash
python app.py --manga naruto --volume-number 10
```
