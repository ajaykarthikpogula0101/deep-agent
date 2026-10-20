"""Build the Windows bundle for non-technical installs: dist/Robin-win64.zip.

Contents: an embeddable CPython (no installer, no PATH changes), every runtime requirement pre-installed,
the app and its static widget, `.env.example`, `Start Robin.bat` and a one-page README. The person unzips it
anywhere and double-clicks `Start Robin.bat`; app.launch does the rest (embedded Postgres, first-run setup
page, crawl, server, browser).

Usage (from the repo root, any Python 3.11+ with network access):
    python scripts/build_bundle.py [--work C:\\rb] [--out dist]

The work dir should be short: the embedding stack ships files whose paths exceed Windows' 260-char limit
under a long folder. `onnx/backend/test` (test data, ~25 MB, the longest paths) is removed from the bundle.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_VER = "3.11.9"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
APP_FILES = ["app", "static", ".env.example", "requirements.txt", "docs/LIGHT_INSTALL.md"]
PRUNE = ["onnx/backend/test", "pip/_vendor/distlib/t32.exe", "pip/_vendor/distlib/t64.exe"]

START_BAT = r"""@echo off
rem Robin: double-click to start. Keep this window open while you use Robin; close it to stop.
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
echo Starting Robin... your browser will open in a moment.
"%~dp0python\python.exe" -m app.launch
if errorlevel 1 (
  echo.
  echo Robin stopped with an error. The message above says what to fix.
  pause
)
"""

README = """Robin - website assistant

1. Unzip this folder anywhere (a short path such as C:\\Robin is best).
2. Double-click "Start Robin.bat". A black window opens; keep it open while you use Robin.
3. Your browser opens the setup page: enter the website Robin should answer about, your name and email,
   a booking link if you have one, and an AI key if you have one (without it Robin quotes the site text).
4. Robin reads the website (about a minute), then opens. Next time, Start Robin.bat opens it directly.

Where things live: your settings are in the file ".env"; the knowledge base and chat history are in "data".
Delete the "data" folder to start over. To stop Robin, close the black window.
"""


def log(msg: str) -> None:
    print(f"[bundle] {msg}", flush=True)


def download(url: str, dest: Path) -> None:
    if dest.exists():
        log(f"cached {dest.name}")
        return
    log(f"downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    log(" ".join(str(c) for c in cmd[-3:]))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=r"C:\rb", help="short build directory")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--keep", action="store_true", help="keep the unzipped bundle in --work")
    args = ap.parse_args()
    t0 = time.time()

    work = Path(args.work)
    bundle = work / "Robin"
    cache = work / "cache"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    # 1. embeddable Python
    py_zip = cache / f"python-{PY_VER}-embed-amd64.zip"
    download(PY_URL, py_zip)
    pydir = bundle / "python"
    with zipfile.ZipFile(py_zip) as z:
        z.extractall(pydir)
    pth = next(pydir.glob("python*._pth"))
    pth.write_text("python311.zip\n.\n..\nLib\\site-packages\nimport site\n", encoding="utf-8")
    python = pydir / "python.exe"

    # 2. pip + runtime requirements
    get_pip = cache / "get-pip.py"
    download(GET_PIP_URL, get_pip)
    run([str(python), str(get_pip), "--no-warn-script-location", "-q"])
    run([str(python), "-m", "pip", "install", "-q", "--no-warn-script-location", "-r", str(ROOT / "requirements.txt")])
    site = pydir / "Lib" / "site-packages"
    for rel in PRUNE:
        p = site / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    for cache_dir in site.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)

    # 3. the app
    for rel in APP_FILES:
        src = ROOT / rel
        dst = bundle / rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
    (bundle / "Start Robin.bat").write_text(START_BAT, encoding="ascii")
    (bundle / "README.txt").write_text(README, encoding="utf-8")

    # 4. smoke: the bundled interpreter imports the app without the repo on sys.path
    run([str(python), "-c", "import app.launch, app.main, pgserver, fastembed; print('bundle imports ok')"], cwd=bundle)

    # 5. zip
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / "Robin-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=work, base_dir="Robin")
    size = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
    log(f"unzipped {size / 1e6:.0f} MB, zip {zip_path.stat().st_size / 1e6:.0f} MB -> {zip_path} ({time.time() - t0:.0f}s)")
    if not args.keep:
        shutil.rmtree(bundle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
