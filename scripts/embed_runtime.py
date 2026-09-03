#!/usr/bin/env python3
"""Download and stage the official Windows embeddable CPython for Release zips.

Pins must match scripts/fetch-runtime.ps1 (same URL, SHA256, MD5).
The embed zip already contains LICENSE.txt (PSF license stack). Keep it.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

# Keep in sync with scripts/fetch-runtime.ps1
EMBED_VERSION = "3.12.10"
EMBED_ZIP_NAME = f"python-{EMBED_VERSION}-embed-amd64.zip"
EMBED_URL = f"https://www.python.org/ftp/python/{EMBED_VERSION}/{EMBED_ZIP_NAME}"
EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
EMBED_MD5 = "fe8ef205f2e9c3ba44d0cf9954e1abd3"

UA = "TruthDecodes-instance-mod-updater-embed/0.1 (+https://github.com/TruthDecodes/instance-mod-updater)"


def download_embed_zip(timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(EMBED_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        blob = resp.read()
    sha = hashlib.sha256(blob).hexdigest()
    md5 = hashlib.md5(blob).hexdigest()
    if sha != EMBED_SHA256 or md5 != EMBED_MD5:
        raise RuntimeError(
            f"checksum mismatch for {EMBED_ZIP_NAME} (sha256={sha} md5={md5})"
        )
    return blob


def stage_embed_runtime(dest_python_dir: Path, blob: bytes | None = None) -> None:
    """Extract the official embed zip into dest_python_dir and fix ._pth paths."""
    if blob is None:
        blob = download_embed_zip()
    dest_python_dir = dest_python_dir.resolve()
    if dest_python_dir.exists():
        import shutil

        shutil.rmtree(dest_python_dir)
    dest_python_dir.mkdir(parents=True)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        if "LICENSE.txt" not in names:
            raise RuntimeError("official embed zip is missing LICENSE.txt; refusing to stage")
        zf.extractall(dest_python_dir)

    pth_files = list(dest_python_dir.glob("python*._pth"))
    if not pth_files:
        raise RuntimeError("python*._pth missing after embed extract")
    # Allow importing the app package from the install root (two levels up).
    pth_files[0].write_text(
        "python312.zip\n.\n../..\nimport site\n",
        encoding="ascii",
    )
    if not (dest_python_dir / "python.exe").is_file():
        raise RuntimeError("python.exe missing after embed extract")
    if not (dest_python_dir / "LICENSE.txt").is_file():
        raise RuntimeError("LICENSE.txt missing after embed extract")
