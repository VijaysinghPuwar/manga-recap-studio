from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path


APP_FILE = "gui_panels.py"
ENV_FILE = ".env"
ENV_EXAMPLE_FILE = ".env.example"
MIN_PYTHON = (3, 10)
REQ_HASH_FILE = ".requirements.hash"


def _venv_python(venv_dir: Path) -> Path:
    if platform.system().lower().startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"\n> {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd))


def _ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        version = ".".join(str(x) for x in MIN_PYTHON)
        raise SystemExit(
            f"Python {version}+ is required. You are using "
            f"{platform.python_version()}."
        )


def _ensure_env_file(root: Path) -> None:
    env_path = root / ENV_FILE
    example_path = root / ENV_EXAMPLE_FILE
    if env_path.exists() or not example_path.exists():
        return
    shutil.copyfile(example_path, env_path)
    print(
        "\nCreated .env from .env.example. Add your OPENAI_API_KEY there "
        "before generating narration."
    )


def _ensure_venv(root: Path) -> Path:
    venv_dir = root / ".venv"
    py = _venv_python(venv_dir)
    if not py.exists():
        _run([sys.executable, "-m", "venv", str(venv_dir)], root)

    requirements = root / "requirements.txt"
    current_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    hash_path = venv_dir / REQ_HASH_FILE
    previous_hash = hash_path.read_text(encoding="utf-8").strip() if hash_path.exists() else ""

    if current_hash != previous_hash:
        _run([str(py), "-m", "pip", "install", "--upgrade", "pip"], root)
        _run([str(py), "-m", "pip", "install", "-r", "requirements.txt"], root)
        hash_path.write_text(current_hash, encoding="utf-8")
    else:
        print("\nDependencies are already installed.")
    return py


def main() -> None:
    root = Path(__file__).resolve().parent
    _ensure_python_version()
    _ensure_env_file(root)
    py = _ensure_venv(root)
    _run([str(py), "-m", "streamlit", "run", APP_FILE], root)


if __name__ == "__main__":
    main()
