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
import json
import os
import re
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

# Linux / macOS: a portable CPython (python-build-standalone) plus wheels pip resolves for that platform
# from this machine. Packaged as .tar.gz so executable bits survive. Tested on Linux x64 (WSL); macOS untested.
PBS_RELEASE = "20261013"
PBS_PY = "3.11.17"
PLATFORMS = {
    "linux-x64": {"pbs": "x86_64-unknown-linux-gnu",
                  "pip": ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64", "linux_x86_64"]},
    "macos-arm64": {"pbs": "aarch64-apple-darwin",
                    "pip": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64"]},
    "macos-x64": {"pbs": "x86_64-apple-darwin",
                  "pip": ["macosx_10_9_x86_64", "macosx_10_15_x86_64", "macosx_11_0_x86_64", "macosx_12_0_x86_64"]},
}

START_SH = """#!/bin/sh
# Robin: run this file to start. Keep the terminal open while you use Robin; Ctrl+C stops it.
cd "$(dirname "$0")"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
[ -d models ] && export FASTEMBED_CACHE_PATH="$(pwd)/models" HF_HUB_OFFLINE=1
echo "Starting Robin... your browser will open in a moment."
exec ./python/bin/python3 -m app.launch "$@"
"""

UPDATE_SH = """#!/bin/sh
# Robin updater: close Robin, then run this. Reads UPDATE_URL from .env; keeps .env, data/ and uploads/.
set -e
cd "$(dirname "$0")"
url=$(sed -n 's/^UPDATE_URL=\\([^#]*\\).*/\\1/p' .env 2>/dev/null | tr -d ' ')
[ -n "$url" ] || { echo "No UPDATE_URL in .env: this install does not know where updates are published."; exit 2; }
local_v=$(head -1 VERSION 2>/dev/null || echo 0)
tmp=$(mktemp -d)
curl -fsSL "$url" -o "$tmp/manifest.json"
ver=$(sed -n 's/.*"version": *"\\([^"]*\\)".*/\\1/p' "$tmp/manifest.json")
pkg=$(sed -n 's/.*"archive": *"\\([^"]*\\)".*/\\1/p' "$tmp/manifest.json")
sum=$(sed -n 's/.*"sha256": *"\\([^"]*\\)".*/\\1/p' "$tmp/manifest.json")
echo "Installed: $local_v   Available: $ver"
[ "$ver" != "$local_v" ] || { echo "Robin is up to date."; rm -rf "$tmp"; exit 0; }
case "$pkg" in http*) full="$pkg";; *) full="$(dirname "$url")/$pkg";; esac
echo "Downloading $full ..."
curl -fL "$full" -o "$tmp/robin.tar.gz"
got=$(sha256sum "$tmp/robin.tar.gz" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$tmp/robin.tar.gz" | cut -d' ' -f1)
[ "$got" = "$sum" ] || { echo "Download did not verify (sha256 mismatch). Nothing was changed."; rm -rf "$tmp"; exit 5; }
tar -xzf "$tmp/robin.tar.gz" -C "$tmp"
new=$(find "$tmp" -maxdepth 2 -name app -type d | head -1 | xargs dirname)
for item in app static python models docs VERSION README.txt start-robin.sh update.sh requirements.txt; do
  [ -e "$new/$item" ] || continue
  rm -rf "./$item"; mv "$new/$item" "./$item"
done
chmod +x start-robin.sh update.sh python/bin/* 2>/dev/null || true
rm -rf "$tmp"
echo "Updated to $ver. Your settings (.env) and data folder were kept."
"""

START_BAT = r"""@echo off
rem Robin: double-click to start. Keep this window open while you use Robin; close it to stop.
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
if exist "%~dp0models" set FASTEMBED_CACHE_PATH=%~dp0models
if exist "%~dp0models" set HF_HUB_OFFLINE=1
echo Starting Robin... your browser will open in a moment.
"%~dp0python\python.exe" -m app.launch
if errorlevel 1 (
  echo.
  echo Robin stopped with an error. The message above says what to fix.
  pause
)
"""

UPDATE_BAT = r"""@echo off
rem Robin: install the latest version. Close the Robin window first.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
pause
"""

README = """Robin - website assistant

1. Unzip this folder anywhere (a short path such as C:\\Robin is best).
2. Double-click "Start Robin.bat" (or Robin.exe). A black window opens; keep it open while you use Robin.
3. Your browser opens the setup page: enter the website Robin should answer about, your name and email,
   a booking link if you have one, and an AI key if you have one (without it Robin quotes the site text).
4. Robin reads the website (about a minute), then opens. Next time, Start Robin.bat opens it directly.

Where things live: your settings are in the file ".env"; the knowledge base and chat history are in "data".
Delete the "data" folder to start over. To stop Robin, close the black window.
Updates: close Robin, double-click "Update Robin.bat". Your settings and data are kept.
"""


def log(msg: str) -> None:
    print(f"[bundle] {msg}", flush=True)


def _app_version() -> str:
    """APP_VERSION from app/main.py, the same string the console shows; updates compare against it."""
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', (ROOT / "app" / "main.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0"


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def prefetch_model(models: Path, python: str) -> None:
    """Download the embedding model into models/ with the given interpreter (any platform: the files are
    platform-independent ONNX + tokenizer files, so the host interpreter can fetch them for another target)."""
    models.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, FASTEMBED_CACHE_PATH=str(models), PYTHONUTF8="1")
    log("pre-downloading the embedding model")
    subprocess.run([python, "-c", "from fastembed import TextEmbedding; "
                    "TextEmbedding('BAAI/bge-small-en-v1.5'); print('model cached')"], env=env, check=True)
    shutil.rmtree(models / "tmp", ignore_errors=True)
    for junk in models.rglob(".locks"):
        shutil.rmtree(junk, ignore_errors=True)


def _extract_pbs(tgz: Path, dest: Path) -> None:
    """Unpack a python-build-standalone tarball on a Windows host.

    Only python/bin and python/lib are needed at runtime; share/ (terminfo has dirs differing only by case,
    impossible on NTFS), include/ and the test suites are skipped. Symlinks (bin/python3 -> python3.11) become
    file copies, since Windows cannot create them without privileges; modes are set again when packaging.
    """
    import tarfile

    skip_prefixes = ("python/share/", "python/include/", "python/lib/python3.11/test/",
                     "python/lib/python3.11/idlelib/", "python/lib/python3.11/tkinter/", "python/lib/tcl8")
    with tarfile.open(tgz) as t:
        members = {m.name: m for m in t.getmembers()}
        for m in members.values():
            if not m.name.startswith("python/") or m.name.startswith(skip_prefixes):
                continue
            target = dest / m.name[len("python/"):]
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            src = m
            if m.issym() or m.islnk():
                link = m.linkname if m.islnk() else os.path.normpath(os.path.join(os.path.dirname(m.name), m.linkname))
                src = members.get(link.replace("\\", "/"))
                if src is None or not src.isfile():
                    continue
            if not src.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(src) as f, open(target, "wb") as out:
                shutil.copyfileobj(f, out)


def copy_app(bundle: Path) -> str:
    for rel in APP_FILES:
        src, dst = ROOT / rel, bundle / rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
    version = _app_version()
    (bundle / "VERSION").write_text(version + "\n", encoding="ascii")
    return version


def build_posix(args, platform: str) -> int:
    """linux-x64 / macos-arm64 / macos-x64: portable CPython + cross-resolved wheels, as .tar.gz."""
    import tarfile

    spec = PLATFORMS[platform]
    work = Path(args.work)
    name = f"Robin-{platform}"
    bundle = work / name
    cache = work / "cache"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    t0 = time.time()

    # 1. portable CPython
    asset = f"cpython-{PBS_PY}+{PBS_RELEASE}-{spec['pbs']}-install_only.tar.gz"
    tgz = cache / asset
    download(f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}/{asset}", tgz)
    _extract_pbs(tgz, bundle / "python")
    site = bundle / "python" / "lib" / f"python{PBS_PY.rsplit('.', 1)[0]}" / "site-packages"

    # 2. wheels for the target platform, resolved by this machine's pip (binary wheels only)
    plat_args = [a for p in spec["pip"] for a in ("--platform", p)]
    run([sys.executable, "-m", "pip", "install", "-q", "--target", str(site), "--only-binary=:all:",
         "--implementation", "cp", "--python-version", PBS_PY.rsplit(".", 1)[0], *plat_args,
         "-r", str(ROOT / "requirements.txt")])
    for rel in PRUNE:
        p = site / rel
        if p.is_dir():
            shutil.rmtree(p)
    for cache_dir in site.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)

    # 3. app, scripts, model
    version = copy_app(bundle)
    (bundle / "start-robin.sh").write_text(START_SH, encoding="ascii", newline="\n")
    (bundle / "update.sh").write_text(UPDATE_SH, encoding="ascii", newline="\n")
    (bundle / "README.txt").write_text(README.replace("Start Robin.bat", "start-robin.sh").replace(
        "Update Robin.bat", "update.sh").replace(" (or Robin.exe)", "").replace("A black window", "A terminal"),
        encoding="utf-8")
    if not args.no_model:
        prefetch_model(bundle / "models", sys.executable)

    # 4. tar.gz with executable bits (this host is Windows: set them explicitly)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tgz_out = out / f"{name}.tar.gz"

    def _mode(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        rel = ti.name.split("/", 1)[1] if "/" in ti.name else ""
        if ti.isdir() or rel.startswith("python/bin/") or rel.endswith((".sh", ".so", ".dylib")) \
                or "/pgserver/pginstall/bin/" in rel or "/pgserver/pginstall/lib/" in rel:
            ti.mode = 0o755
        else:
            ti.mode = 0o644
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "robin"
        return ti

    # dereference=True: the Hugging Face model cache links snapshots/ -> blobs/; a symlink made on this
    # Windows host has a Windows-style target that is dead on Linux/macOS, so store real files instead.
    with tarfile.open(tgz_out, "w:gz", compresslevel=6, dereference=True) as t:
        t.add(bundle, arcname=name, filter=_mode)
    manifest = {"version": version, "archive": tgz_out.name, "sha256": _sha256(tgz_out),
                "size": tgz_out.stat().st_size, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "platform": platform}
    (out / f"manifest-{platform}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
    log(f"{platform}: unpacked {size / 1e6:.0f} MB, archive {tgz_out.stat().st_size / 1e6:.0f} MB -> {tgz_out} "
        f"+ manifest-{platform}.json ({time.time() - t0:.0f}s). Untested on macOS.")
    if not args.keep:
        shutil.rmtree(bundle)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="win-x64", choices=["win-x64", *PLATFORMS],
                    help="win-x64 (default) builds the zip with the embeddable Python; others build a .tar.gz")
    ap.add_argument("--work", default=r"C:\rb", help="short build directory")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--keep", action="store_true", help="keep the unzipped bundle in --work")
    ap.add_argument("--no-model", action="store_true",
                    help="do not pre-download the embedding model (smaller zip, slower first run)")
    ap.add_argument("--llm-key-file", help="file holding Champions' central AI key; shipped in .env.example "
                                           "so the setup page does not ask for one (use a spend-capped key)")
    ap.add_argument("--llm-base-url", default="https://openrouter.ai/api/v1")
    ap.add_argument("--chat-model", default="openai/gpt-4.1-mini")
    args = ap.parse_args()
    if args.platform != "win-x64":
        return build_posix(args, args.platform)
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
    (bundle / "Update Robin.bat").write_text(UPDATE_BAT, encoding="ascii")
    shutil.copy(ROOT / "scripts" / "bundle" / "update.ps1", bundle / "update.ps1")
    (bundle / "README.txt").write_text(README, encoding="utf-8")
    version = _app_version()
    (bundle / "VERSION").write_text(version + "\n", encoding="ascii")

    # 3a. Robin.exe: the double-click entry point, compiled with the C# compiler .NET Framework ships
    csc = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if csc.exists():
        run([str(csc), "/nologo", "/optimize", "/target:exe", f"/out:{bundle / 'Robin.exe'}",
             str(ROOT / "scripts" / "bundle" / "Robin.cs")])
    else:
        log("csc.exe not found: no Robin.exe, Start Robin.bat is the entry point")

    # 3b. central AI key (optional): shipped in .env.example, which becomes .env on first start
    if args.llm_key_file:
        key = Path(args.llm_key_file).read_text(encoding="utf-8").strip()
        env_example = bundle / ".env.example"
        text = env_example.read_text(encoding="utf-8")
        for k, v in (("LLM_API_KEY", key), ("LLM_BASE_URL", args.llm_base_url), ("CHAT_MODEL", args.chat_model)):
            text = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", text)
        env_example.write_text(text, encoding="utf-8")
        log("central AI key written to the bundle's .env.example (setup page will not ask for one)")

    # 3c. the embedding model, so the first crawl needs no 130 MB download
    if not args.no_model:
        models = bundle / "models"
        models.mkdir()
        env = dict(os.environ, FASTEMBED_CACHE_PATH=str(models), PYTHONUTF8="1")
        log("pre-downloading the embedding model")
        subprocess.run([str(python), "-c", "from fastembed import TextEmbedding; "
                        "TextEmbedding('BAAI/bge-small-en-v1.5'); print('model cached')"],
                       cwd=bundle, env=env, check=True)
        shutil.rmtree(models / "tmp", ignore_errors=True)
        for junk in models.rglob(".locks"):
            shutil.rmtree(junk, ignore_errors=True)

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
    # manifest.json next to the zip: publish both at UPDATE_URL's folder and installs can update themselves
    manifest = {"version": version, "zip": zip_path.name, "sha256": _sha256(zip_path),
                "size": zip_path.stat().st_size, "built": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log(f"unzipped {size / 1e6:.0f} MB, zip {zip_path.stat().st_size / 1e6:.0f} MB -> {zip_path} "
        f"+ manifest.json (version {version}) ({time.time() - t0:.0f}s)")
    if not args.keep:
        shutil.rmtree(bundle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
