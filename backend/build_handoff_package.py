"""
Build an offline macOS handoff package for this repository.

The package contains:
- live secrets for backend/.env and Google Sheets export
- private statement PDFs
- an offline Apple Silicon runtime bootstrap (Python + wheelhouse + JDK)
- a one-click macOS installer

Usage:
    cd backend && python build_handoff_package.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from app.config import BACKEND_DIR, REPO_ROOT, settings


PYTHON_BUILD_STANDALONE_RELEASES_API = "https://api.github.com/repos/indygreg/python-build-standalone/releases"
ADOPTIUM_JDK_API = (
    "https://api.adoptium.net/v3/assets/latest/11/hotspot"
    "?architecture=aarch64&image_type=jdk&os=mac"
)
PYTHON_ASSET_HINT = "aarch64-apple-darwin-install_only.tar.gz"
PYTHON_VERSION_HINT = "cpython-3.11"


def build_handoff_package(output_root: Path) -> Path:
    git_commit = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).strip()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    package_dir = output_root / f"expense-mac-handoff-{timestamp}"
    payload_dir = package_dir / "payload"
    runtime_dir = payload_dir / "runtime"
    secrets_dir = payload_dir / "secrets"
    package_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)

    env_template_path = secrets_dir / "backend.env.template"
    service_account_path = _write_secrets(secrets_dir, env_template_path)
    pdf_archive = payload_dir / "statements-pdfs.tar.gz"
    _write_pdf_archive(pdf_archive)

    python_archive = runtime_dir / "python-build-standalone.tar.gz"
    python_url = _download_python_runtime(python_archive)

    jdk_archive = runtime_dir / "openjdk-mac-arm64.tar.gz"
    jdk_url = _download_jdk(jdk_archive)

    wheelhouse_dir = runtime_dir / "wheelhouse"
    _download_wheelhouse(wheelhouse_dir)

    installer_path = package_dir / "install-mac.command"
    _write_installer(
        installer_path=installer_path,
        git_commit=git_commit,
        env_template_rel=env_template_path.relative_to(package_dir).as_posix(),
        pdf_archive_rel=pdf_archive.relative_to(package_dir).as_posix(),
        python_archive_rel=python_archive.relative_to(package_dir).as_posix(),
        wheelhouse_rel=wheelhouse_dir.relative_to(package_dir).as_posix(),
        jdk_archive_rel=jdk_archive.relative_to(package_dir).as_posix(),
        service_account_rel=service_account_path.relative_to(package_dir).as_posix(),
    )

    _write_readme(package_dir, git_commit)
    _write_manifest(
        package_dir=package_dir,
        git_commit=git_commit,
        python_url=python_url,
        jdk_url=jdk_url,
    )

    zip_path = output_root / f"{package_dir.name}.zip"
    _zip_directory(package_dir, zip_path)
    return zip_path


def _write_secrets(secrets_dir: Path, env_template_path: Path) -> Path:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"Expected backend env at {env_path}")

    raw_env = env_path.read_text(encoding="utf-8")
    google_key_path = _read_env_value(raw_env, "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    if not google_key_path:
        raise ValueError("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON is not configured in backend/.env")

    google_key_file = Path(google_key_path)
    if not google_key_file.exists():
        raise FileNotFoundError(f"Google service account key not found: {google_key_file}")

    templated_lines: list[str] = []
    for line in raw_env.splitlines():
        if line.startswith("DATABASE_URL="):
            templated_lines.append("DATABASE_URL=__BACKEND_SQLITE_URL__")
        elif line.startswith("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON="):
            templated_lines.append("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON=__SERVICE_ACCOUNT_JSON__")
        else:
            templated_lines.append(line)
    env_template_path.write_text("\n".join(templated_lines) + "\n", encoding="utf-8")

    service_account_target = secrets_dir / "google-service-account.json"
    shutil.copy2(google_key_file, service_account_target)
    return service_account_target


def _write_pdf_archive(output_path: Path) -> None:
    with tarfile.open(output_path, "w:gz") as tar:
        for pdf_path in sorted((REPO_ROOT / "statements").rglob("*.pdf")):
            tar.add(pdf_path, arcname=pdf_path.relative_to(REPO_ROOT))


def _download_python_runtime(destination: Path) -> str:
    releases = _fetch_json(PYTHON_BUILD_STANDALONE_RELEASES_API)
    asset_url = None
    for release in releases:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if PYTHON_VERSION_HINT in name and PYTHON_ASSET_HINT in name:
                asset_url = asset.get("browser_download_url")
                break
        if asset_url:
            break
    if not asset_url:
        raise RuntimeError("Could not find a macOS arm64 Python 3.11 standalone runtime asset.")
    _download_file(asset_url, destination)
    return asset_url


def _download_jdk(destination: Path) -> str:
    assets = _fetch_json(ADOPTIUM_JDK_API)
    if not assets:
        raise RuntimeError("Could not find a macOS arm64 JDK 11 asset.")
    package_info = assets[0]["binary"]["package"]
    url = package_info["link"]
    _download_file(url, destination)
    return url


def _download_wheelhouse(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(destination),
        "--platform",
        "macosx_11_0_arm64",
        "--python-version",
        "311",
        "--implementation",
        "cp",
        "--abi",
        "cp311",
        "--only-binary=:all:",
        "-r",
        str(BACKEND_DIR / "requirements.txt"),
    ]
    _run(command, cwd=REPO_ROOT)


def _write_installer(
    *,
    installer_path: Path,
    git_commit: str,
    env_template_rel: str,
    pdf_archive_rel: str,
    python_archive_rel: str,
    wheelhouse_rel: str,
    jdk_archive_rel: str,
    service_account_rel: str,
) -> None:
    content = f"""#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR"
BASELINE_COMMIT="{git_commit}"
ENV_TEMPLATE_REL="{env_template_rel}"
PDF_ARCHIVE_REL="{pdf_archive_rel}"
PYTHON_ARCHIVE_REL="{python_archive_rel}"
WHEELHOUSE_REL="{wheelhouse_rel}"
JDK_ARCHIVE_REL="{jdk_archive_rel}"
SERVICE_ACCOUNT_REL="{service_account_rel}"

find_repo_dir() {{
  if [[ -d "$PACKAGE_DIR/.git" ]]; then
    printf '%s\\n' "$PACKAGE_DIR"
    return 0
  fi
  if [[ -d "$PACKAGE_DIR/../.git" ]]; then
    printf '%s\\n' "$(cd "$PACKAGE_DIR/.." && pwd)"
    return 0
  fi
  if [[ -d "$PACKAGE_DIR/../expense/.git" ]]; then
    printf '%s\\n' "$(cd "$PACKAGE_DIR/../expense" && pwd)"
    return 0
  fi
  if [[ -d "$(pwd)/.git" ]]; then
    pwd
    return 0
  fi
  printf 'Unable to locate the cloned expense repo. Run this from the repo root or unzip the handoff package beside the clone.\\n' >&2
  exit 1
}}

REPO_DIR="$(find_repo_dir)"
if ! git -C "$REPO_DIR" merge-base --is-ancestor "$BASELINE_COMMIT" HEAD; then
  printf 'Repo HEAD must include baseline commit %s before installing this handoff package.\\n' "$BASELINE_COMMIT" >&2
  exit 1
fi

HANDOFF_DIR="$REPO_DIR/.handoff"
SECRETS_DIR="$HANDOFF_DIR/secrets"
RUNTIME_DIR="$HANDOFF_DIR/runtime"
QUARANTINE_DIR="$HANDOFF_DIR/quarantine/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SECRETS_DIR" "$RUNTIME_DIR" "$QUARANTINE_DIR"

for stale in "$REPO_DIR/.env" "$REPO_DIR/expense_tracker.db"; do
  if [[ -e "$stale" ]]; then
    mv "$stale" "$QUARANTINE_DIR/"
  fi
done

cp "$PACKAGE_DIR/$SERVICE_ACCOUNT_REL" "$SECRETS_DIR/google-service-account.json"

BACKEND_DB_PATH="$REPO_DIR/backend/expense_tracker.db"
DATABASE_URL="sqlite:///$BACKEND_DB_PATH"
SERVICE_ACCOUNT_PATH="$SECRETS_DIR/google-service-account.json"
sed \
  -e "s|__BACKEND_SQLITE_URL__|$DATABASE_URL|g" \
  -e "s|__SERVICE_ACCOUNT_JSON__|$SERVICE_ACCOUNT_PATH|g" \
  "$PACKAGE_DIR/$ENV_TEMPLATE_REL" > "$REPO_DIR/backend/.env"

tar -xzf "$PACKAGE_DIR/$PDF_ARCHIVE_REL" -C "$REPO_DIR"

rm -rf "$RUNTIME_DIR/python-dist" "$RUNTIME_DIR/venv" "$RUNTIME_DIR/jdk"
mkdir -p "$RUNTIME_DIR/python-dist" "$RUNTIME_DIR/jdk"
tar -xzf "$PACKAGE_DIR/$PYTHON_ARCHIVE_REL" -C "$RUNTIME_DIR/python-dist"
PYTHON_BIN="$(find "$RUNTIME_DIR/python-dist" -path '*/bin/python3' -print -quit)"
if [[ -z "$PYTHON_BIN" ]]; then
  printf 'Unable to find python3 inside the packaged standalone runtime.\\n' >&2
  exit 1
fi
"$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$PYTHON_BIN" -m venv "$RUNTIME_DIR/venv"
source "$RUNTIME_DIR/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install --no-index --find-links "$PACKAGE_DIR/$WHEELHOUSE_REL" -r "$REPO_DIR/backend/requirements.txt"

tar -xzf "$PACKAGE_DIR/$JDK_ARCHIVE_REL" -C "$RUNTIME_DIR/jdk"
JDK_ROOT="$(find "$RUNTIME_DIR/jdk" -maxdepth 1 -type d -name 'jdk*' -print -quit)"
if [[ -z "$JDK_ROOT" ]]; then
  printf 'Unable to find the extracted JDK directory.\\n' >&2
  exit 1
fi
if [[ -d "$JDK_ROOT/Contents/Home" ]]; then
  JAVA_HOME="$JDK_ROOT/Contents/Home"
else
  JAVA_HOME="$JDK_ROOT"
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"

rm -f "$BACKEND_DB_PATH"
(
  cd "$REPO_DIR/backend"
  alembic upgrade head
  python setup_database.py
  python import_statements.py --skip-recurring-charges --allow-validation-errors all
  python import_rewards_history.py
  python import_live_state.py
)

cat > "$REPO_DIR/start-expense.command" <<EOF
#!/bin/bash
set -euo pipefail
REPO_DIR="$REPO_DIR"
export JAVA_HOME="$JAVA_HOME"
export PATH="$RUNTIME_DIR/venv/bin:$JAVA_HOME/bin:$PATH"
cd "$REPO_DIR/backend"
python run.py
EOF
chmod +x "$REPO_DIR/start-expense.command"

cat > "$REPO_DIR/dev-shell.command" <<EOF
#!/bin/bash
set -euo pipefail
REPO_DIR="$REPO_DIR"
export JAVA_HOME="$JAVA_HOME"
export PATH="$RUNTIME_DIR/venv/bin:$JAVA_HOME/bin:$PATH"
cd "$REPO_DIR"
exec bash -l
EOF
chmod +x "$REPO_DIR/dev-shell.command"

cat > "$HANDOFF_DIR/install-report.txt" <<EOF
Installed at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Baseline commit: $BASELINE_COMMIT
Repo dir: $REPO_DIR
Database: $BACKEND_DB_PATH
Service account: $SERVICE_ACCOUNT_PATH
JAVA_HOME: $JAVA_HOME
EOF

open "$REPO_DIR/start-expense.command"
"""
    installer_path.write_text(content, encoding="utf-8")
    installer_path.chmod(0o755)


def _write_readme(package_dir: Path, git_commit: str) -> None:
    text = f"""# Expense Mac Handoff Package

Baseline commit: `{git_commit}`

1. Clone the repo so your local checkout includes commit `{git_commit}` or newer.
2. Unzip this package next to the clone or inside the clone root.
3. Run `install-mac.command`.

The installer writes live secrets into `backend/.env`, restores private PDFs, rebuilds
`backend/expense_tracker.db` from git-tracked statement JSON plus `state/live_state.json`,
and starts the app from the packaged offline Apple Silicon runtime.
"""
    (package_dir / "README.md").write_text(text, encoding="utf-8")


def _write_manifest(package_dir: Path, git_commit: str, python_url: str, jdk_url: str) -> None:
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "git_commit": git_commit,
        "python_runtime_url": python_url,
        "jdk_url": jdk_url,
        "files": [],
    }
    for path in sorted(package_dir.rglob("*")):
        if path.is_file():
            manifest["files"].append(
                {
                    "path": path.relative_to(package_dir).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    (package_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            zf.write(path, arcname=source_dir.name + "/" + path.relative_to(source_dir).as_posix())


def _read_env_value(raw_env: str, key: str) -> str:
    prefix = f"{key}="
    for line in raw_env.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "expense-handoff-builder"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "expense-handoff-builder"})
    with urllib.request.urlopen(request) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline macOS handoff package.")
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "handoff_out"),
        help="Directory that will receive the generated package zip.",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    zip_path = build_handoff_package(output_root)
    print(f"Built handoff package: {zip_path}")


if __name__ == "__main__":
    main()
