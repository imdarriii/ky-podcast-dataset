"""Publish web/ to a public Netlify URL."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
SITE_ZIP = Path(__file__).resolve().parent / "site_deploy.zip"
SKIP = {"dataset.zip"}
SKIP_SUFFIX = {".wav"}


def log(msg: str) -> None:
    print(msg, flush=True)


def build_zip() -> None:
    if SITE_ZIP.exists():
        SITE_ZIP.unlink()
    log("writing " + str(SITE_ZIP))
    n = 0
    with zipfile.ZipFile(SITE_ZIP, "w", zipfile.ZIP_STORED) as z:
        for p in WEB.rglob("*"):
            if not p.is_file() or p.name in SKIP or p.suffix.lower() in SKIP_SUFFIX:
                continue
            z.write(p, p.relative_to(WEB).as_posix())
            n += 1
            if n % 5 == 0:
                log(f"  packed {n} files")
    log(f"packed {n} files, {SITE_ZIP.stat().st_size} bytes")


def netlify() -> dict:
    log("POST api.netlify.com/api/v1/sites")
    proc = subprocess.run(
        [
            "curl", "-sS",
            "-H", "Content-Type: application/zip",
            "--data-binary", f"@{SITE_ZIP}",
            "https://api.netlify.com/api/v1/sites",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        log(proc.stderr)
        sys.exit(proc.returncode)
    log(proc.stdout[:2000])
    return json.loads(proc.stdout)


def main() -> None:
    build_zip()
    site = netlify()
    url = site.get("ssl_url") or site.get("url")
    log("PUBLIC " + str(url))


if __name__ == "__main__":
    main()
