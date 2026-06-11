import sys
import os
import logging
import subprocess
import zipfile
import shutil
import tempfile
import time
import hashlib
import re
import uuid
import requests
from pathlib import Path
from typing import Optional

from packaging import version
from PyQt6.QtCore import QObject, pyqtSignal

# --- CONFIGURATION ---
GITHUB_REPO = "c0pper22/PmGen"
ASSET_NAME = "PmGen.zip"
CURRENT_VERSION = "2.8.9"
USER_AGENT = f"PmGen-Updater/{CURRENT_VERSION}"
UPDATER_EXE_NAME = "updater.exe"
CHECKSUM_SUFFIX = ".sha256"


def _find_updater_exe_in_tree(root_dir: Path) -> Optional[Path]:
    """Find an updater.exe within root_dir, handling extra top-level ZIP folders."""
    try:
        direct = root_dir / UPDATER_EXE_NAME
        if direct.exists():
            return direct

        candidates = [p for p in root_dir.rglob(UPDATER_EXE_NAME) if p.is_file()]
        if candidates:
            # Prefer the shallowest path in case multiple are present.
            candidates.sort(key=lambda p: (len(p.parts), str(p).lower()))
            return candidates[0]
    except Exception:
        # Best-effort; caller will fall back to other sources.
        return None

    return None


def _stage_updater_exe(updater_source: Path) -> Optional[Path]:
    """Copy updater.exe to a stable temp location and return the staged path."""
    try:
        stage_dir = Path(tempfile.gettempdir()) / "pmgen_updater_stage"
        stage_dir.mkdir(parents=True, exist_ok=True)

        # Best-effort cleanup of staged updaters from previous runs.
        # A copy that is still executing is locked and the unlink simply fails.
        for stale in stage_dir.glob("updater_*.exe"):
            try:
                stale.unlink()
            except OSError:
                pass

        staged_path = stage_dir / f"updater_{uuid.uuid4().hex}.exe"
        shutil.copy2(updater_source, staged_path)
        return staged_path
    except Exception:
        logging.exception("Failed to stage updater executable")
        return None


def _new_update_session_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "pmgen_updates"
    root.mkdir(parents=True, exist_ok=True)
    session_dir = root / f"session_{uuid.uuid4().hex}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _parse_checksum_text(content: str) -> Optional[str]:
    match = re.search(r"\b([A-Fa-f0-9]{64})\b", content or "")
    if not match:
        return None
    return match.group(1).lower()


def _fetch_expected_checksum(url: str, headers: dict[str, str]) -> str:
    checksum_url = f"{url}{CHECKSUM_SUFFIX}"
    response = requests.get(checksum_url, headers=headers, timeout=10)
    response.raise_for_status()
    checksum = _parse_checksum_text(response.text)
    if not checksum:
        raise ValueError(f"Checksum file did not contain a valid SHA-256: {checksum_url}")
    return checksum


def _safe_extract_zip(zip_ref: zipfile.ZipFile, destination: Path, progress_cb) -> None:
    destination_resolved = destination.resolve()
    members = zip_ref.infolist()
    total_files = len(members)

    for index, member in enumerate(members):
        member_target = (destination / member.filename).resolve()
        try:
            member_target.relative_to(destination_resolved)
        except ValueError:
            raise ValueError(f"Unsafe path in update archive: {member.filename}")
        zip_ref.extract(member, destination)
        if total_files > 0:
            pct = int(((index + 1) / total_files) * 100)
            progress_cb(pct)

class UpdateWorker(QObject):
    """
    Handles update logic (check, download, extract) in a background thread
    to prevent freezing the PyQt UI.
    """
    # Signals
    check_finished = pyqtSignal(bool, str, str)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(str)
    extraction_progress = pyqtSignal(int)
    extraction_finished = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.headers = {'User-Agent': USER_AGENT}

    def check_updates(self) -> None:
        """Queries GitHub API to compare current version against the latest release."""
        logging.info("Checking for updates via GitHub API...")
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            latest_tag = data.get('tag_name', '').lstrip('v')
            
            if not latest_tag:
                raise ValueError("Could not retrieve tag name from GitHub.")

            if version.parse(latest_tag) > version.parse(CURRENT_VERSION):
                logging.info(f"Update found: {latest_tag}")
                
                download_url = next(
                    (asset['browser_download_url'] for asset in data.get('assets', []) if asset['name'] == ASSET_NAME),
                    None
                )

                if download_url:
                    self.check_finished.emit(True, latest_tag, download_url)
                else:
                    self.error_occurred.emit(f"Update {latest_tag} found, but asset '{ASSET_NAME}' is missing.")
            else:
                logging.info("System is up to date.")
                self.check_finished.emit(False, latest_tag, "")

        except requests.RequestException as e:
            logging.error(f"Network error during update check: {e}")
            self.error_occurred.emit(f"Network error: {str(e)}")
        except Exception as e:
            logging.exception("Unexpected error during update check.")
            self.error_occurred.emit(f"Error checking updates: {str(e)}")

    def download_update(self, url: str) -> None:
        """Downloads the update ZIP file to a temporary directory."""
        logging.info(f"Downloading update from: {url}")
        
        try:
            session_dir = _new_update_session_dir()
            zip_path = session_dir / ASSET_NAME

            with requests.get(url, headers=self.headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0

                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 100)
                                self.download_progress.emit(pct)

            expected_checksum = _fetch_expected_checksum(url, self.headers)
            actual_checksum = _compute_sha256(zip_path)
            if actual_checksum != expected_checksum:
                raise ValueError(
                    f"Checksum validation failed. expected={expected_checksum} actual={actual_checksum}"
                )

            logging.info("Download complete.")
            self.download_finished.emit(str(zip_path))

        except Exception as e:
            logging.error(f"Download failed: {e}")
            self.error_occurred.emit(f"Download failed: {str(e)}")

    def extract_update(self, zip_path_str: str) -> None:
        """Extracts the downloaded ZIP to a temporary folder."""
        zip_path = Path(zip_path_str)
        try:
            temp_extract_dir = zip_path.parent / "extracted"

            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            temp_extract_dir.mkdir(parents=True, exist_ok=True)

            logging.info(f"Extracting to {temp_extract_dir}")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                _safe_extract_zip(zip_ref, temp_extract_dir, self.extraction_progress.emit)

            self.extraction_finished.emit(str(zip_path), str(temp_extract_dir))

        except Exception as e:
            logging.error(f"Extraction failed: {e}")
            self.error_occurred.emit(f"Extraction failed: {str(e)}")


def perform_restart(zip_path_str: str, temp_extract_dir_str: str) -> bool:
    """
    Terminates the current application and launches an external updater executable
    to move files from temp_extract_dir to the main directory.

    Returns False if the restart could not be initiated (caller should inform the
    user); does not return at all on success (the process exits).
    """
    if not getattr(sys, 'frozen', False):
        logging.warning("Application is not frozen. Skipping restart/update logic.")
        return False

    current_exe = Path(sys.executable)
    current_dir = current_exe.parent
    exe_name = current_exe.name

    # Pre-flight: verify the install directory is writable BEFORE exiting the app.
    # Otherwise the updater fails after the app has already quit and the user is
    # left with a closed application and no visible error.
    try:
        probe = current_dir / f".pmgen_write_test_{uuid.uuid4().hex}"
        probe.touch()
        probe.unlink()
    except OSError as e:
        logging.critical(
            f"Install directory is not writable: {current_dir} ({e}). Aborting update restart."
        )
        return False

    # Prefer an updater shipped in the extracted update payload so the updater can be patched.
    temp_extract_dir = Path(temp_extract_dir_str)
    updater_source = _find_updater_exe_in_tree(temp_extract_dir)
    if updater_source is None:
        updater_source = current_dir / UPDATER_EXE_NAME
        if not updater_source.exists():
            logging.critical(
                "Updater executable not found in update payload or install directory. "
                f"Looked in: {temp_extract_dir} and {current_dir}"
            )
            return False

    # Stage updater to temp before launching. This allows it to overwrite the installed updater.exe.
    staged_updater = _stage_updater_exe(updater_source)
    if staged_updater is None or not staged_updater.exists():
        logging.critical("Failed to stage updater executable; aborting update restart.")
        return False

    zip_path = Path(zip_path_str)
    try:
        if zip_path.exists():
            zip_path.unlink()
    except OSError as e:
        logging.warning(f"Could not delete temp zip: {e}")

    logging.info("Launching external updater and exiting...")

    session_id = Path(temp_extract_dir_str).parent.name

    subprocess.Popen(
        [str(staged_updater), temp_extract_dir_str, str(current_dir), exe_name, str(os.getpid()), session_id],
        cwd=str(current_dir)
    )
    
    sys.exit(0)