"""Secure updater for PmGen.

Fetches GitHub releases, verifies Ed25519-signed manifests, validates
SHA-256 checksums of downloaded artifacts, and orchestrates extraction
and restart.
"""

import sys
import os
import logging
import subprocess
import zipfile
import shutil
import tempfile
import hashlib
import uuid
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import requests
from packaging.version import parse as parse_version
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_REPO = "c0pper22/PmGen3"
ASSET_NAME = "PmGen.zip"
CURRENT_VERSION = "3.0.0"
USER_AGENT = f"PmGen-Updater/{CURRENT_VERSION}"
UPDATER_EXE_NAME = "updater.exe"

GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

MANIFEST_NAME = "manifest.json"
MANIFEST_SIGNATURE_NAME = "manifest.json.sig"
SIGNATURE_ALGORITHM = "ed25519"
UPDATE_STATE_FILE = Path.home() / ".indybiz_pm" / "update_state.json"

# PLACEHOLDER — replace with the real Ed25519 public key (base64-encoded)
# before distributing signed releases.
SIGNING_PUBLIC_KEY_B64 = "7eRA/6NfuOHUgRje6SGSH25vKeV08tuhA1RP5rojiVs="

# Module-level shared state — needed because check and download may run on
# separate UpdateWorker instances in different QThreads.
_pending_update_context: Optional["UpdateDownloadContext"] = None
_verified_zip_paths: set[Path] = set()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedUpdateManifest:
    """A manifest whose Ed25519 signature has been verified."""

    version: str
    asset_name: str
    sha256: str
    size_bytes: int
    release_date: str | None = None
    minimum_supported_version: str | None = None


@dataclass(frozen=True)
class UpdateDownloadContext:
    """Everything needed to download and verify an update."""

    manifest: VerifiedUpdateManifest
    zip_url: str
    release_tag: str


# ---------------------------------------------------------------------------
# Helper: find and stage the updater executable
# ---------------------------------------------------------------------------


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
    """Create a unique temporary directory for an update session."""
    root = Path(tempfile.gettempdir()) / "pmgen_updates"
    root.mkdir(parents=True, exist_ok=True)
    session_dir = root / f"session_{uuid.uuid4().hex}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _compute_sha256(file_path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _safe_extract_zip(zip_ref: zipfile.ZipFile, destination: Path, progress_cb) -> None:
    """Extract a ZIP archive, guarding against path-traversal attacks."""
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


# ---------------------------------------------------------------------------
# Secure-manifest helpers (standalone, testable)
# ---------------------------------------------------------------------------


def _download_bytes(url: str, headers: dict[str, str], timeout: int = 10) -> bytes:
    """Download a small file and return raw bytes. Uses raise_for_status()."""
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.content


def _load_public_key() -> Ed25519PublicKey:
    """Decode SIGNING_PUBLIC_KEY_B64 and return an Ed25519PublicKey."""
    raw = base64.b64decode(SIGNING_PUBLIC_KEY_B64)
    return Ed25519PublicKey.from_public_bytes(raw)


def _verify_manifest_signature(manifest_bytes: bytes, signature_bytes: bytes) -> None:
    """Verify the Ed25519 signature over *manifest_bytes*.  Raises on failure.

    *signature_bytes* is the raw bytes of the ``manifest.json.sig`` file,
    which contains a base64-encoded Ed25519 signature (possibly with
    surrounding whitespace).  This function decodes it before verification.
    """
    try:
        public_key = _load_public_key()
        # Decode the base64-encoded signature to the raw 64-byte Ed25519 signature
        signature = base64.b64decode(signature_bytes.strip())
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature:
        raise ValueError("Manifest signature verification failed: invalid Ed25519 signature.")
    except Exception as exc:
        raise ValueError(f"Manifest signature verification error: {exc}") from exc


def _parse_verified_manifest(manifest_bytes: bytes) -> VerifiedUpdateManifest:
    """Parse and validate a manifest (call ONLY *after* signature verification).

    Validates:
      - schema_version == 1
      - app_id == "PmGen"
      - signature_algorithm == "ed25519"
      - version present and non-empty
      - asset_name == "PmGen.zip"
      - sha256 is 64 hex characters
      - size_bytes > 0
      - minimum_supported_version, if set, is not newer than CURRENT_VERSION
    """
    try:
        data = json.loads(manifest_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Manifest is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object.")

    # --- schema_version ---
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(
            f"Unsupported manifest schema_version: {schema_version!r} (expected 1)"
        )

    # --- app_id ---
    app_id = data.get("app_id")
    if app_id != "PmGen":
        raise ValueError(f"Manifest app_id mismatch: {app_id!r} (expected 'PmGen')")

    # --- signature_algorithm ---
    sig_alg = data.get("signature_algorithm")
    if sig_alg != SIGNATURE_ALGORITHM:
        raise ValueError(
            f"Unsupported signature_algorithm: {sig_alg!r} "
            f"(expected {SIGNATURE_ALGORITHM!r})"
        )

    # --- version ---
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Manifest version is missing or empty.")

    # --- asset_name ---
    asset_name = data.get("asset_name")
    if asset_name != ASSET_NAME:
        raise ValueError(
            f"Manifest asset_name mismatch: {asset_name!r} (expected {ASSET_NAME!r})"
        )

    # --- sha256 ---
    sha256 = data.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError(
            f"Manifest sha256 must be 64 hex characters, got: {sha256!r}"
        )
    # Validate hex characters (case-insensitive)
    try:
        int(sha256, 16)
    except ValueError:
        raise ValueError(f"Manifest sha256 is not valid hex: {sha256!r}")

    # --- size_bytes ---
    size_bytes = data.get("size_bytes")
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        raise ValueError(
            f"Manifest size_bytes must be a positive integer, got: {size_bytes!r}"
        )

    # --- release_date (optional) ---
    release_date = data.get("release_date")

    # --- minimum_supported_version (optional) ---
    minimum_supported_version = data.get("minimum_supported_version")
    if minimum_supported_version is not None:
        try:
            min_ver = parse_version(minimum_supported_version)
            current_ver = parse_version(CURRENT_VERSION)
            if current_ver < min_ver:
                raise ValueError(
                    f"Update requires version >= {minimum_supported_version}, "
                    f"but current version is {CURRENT_VERSION}. "
                    f"Update cannot be applied."
                )
        except ValueError:
            raise  # re-raise our own ValueError
        except Exception as exc:
            raise ValueError(
                f"Invalid minimum_supported_version: {minimum_supported_version!r}"
            ) from exc

    return VerifiedUpdateManifest(
        version=version,
        asset_name=asset_name,
        sha256=sha256.lower(),
        size_bytes=size_bytes,
        release_date=release_date,
        minimum_supported_version=minimum_supported_version,
    )


# ---------------------------------------------------------------------------
# Installed-version tracking
# ---------------------------------------------------------------------------


def _load_last_installed_version() -> str | None:
    """Read the highest installed version from update_state.json.

    Returns None if the file does not exist or cannot be parsed.
    """
    try:
        state = json.loads(UPDATE_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(state, dict):
        return None

    version = state.get("last_installed_version")
    if isinstance(version, str) and version.strip():
        return version
    return None


def _save_last_installed_version(version: str) -> None:
    """Persist the installed version to update_state.json."""
    UPDATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_installed_version": version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    UPDATE_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _validate_not_rollback(candidate_version: str) -> None:
    """Reject the update if *candidate_version* is lower than the last installed."""
    last = _load_last_installed_version()
    if last is None:
        return  # No history — allow

    try:
        if parse_version(candidate_version) < parse_version(last):
            raise ValueError(
                f"Update would rollback from {last} to {candidate_version}. "
                f"This is not supported."
            )
    except ValueError:
        raise  # re-raise our own
    except Exception as exc:
        raise ValueError(
            f"Version comparison failed: {last} vs {candidate_version}"
        ) from exc


# ---------------------------------------------------------------------------
# UpdateWorker
# ---------------------------------------------------------------------------


class UpdateWorker(QObject):
    """Handles secure update logic (check, download, extract) in a background thread.

    The check phase fetches and verifies a signed manifest from the GitHub
    release.  The download phase verifies the ZIP against the manifest's
    SHA-256 before accepting it.  Extraction only proceeds for verified ZIPs.
    """

    # Signals
    check_finished = pyqtSignal(bool, str, str)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(bool, str)
    extraction_progress = pyqtSignal(int)
    extraction_finished = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.headers = {"User-Agent": USER_AGENT}

    # ------------------------------------------------------------------
    # Check for updates
    # ------------------------------------------------------------------

    def check_updates(self) -> None:
        """Fetch the latest GitHub release, verify its signed manifest, and
        decide whether an update is available.

        On success emits ``check_finished(True, version, zip_url)`` when an
        update is available, or ``check_finished(False, current_version, "")``
        when already up-to-date.  Errors are emitted via ``error_occurred``.
        """
        global _pending_update_context

        logger.info("Checking for updates via GitHub API...")
        try:
            release = self._fetch_latest_release()
            release_tag = release["tag_name"]

            # Locate the three required assets
            zip_asset = _find_asset(release, ASSET_NAME)
            manifest_asset = _find_asset(release, MANIFEST_NAME)
            sig_asset = _find_asset(release, MANIFEST_SIGNATURE_NAME)

            missing = []
            if manifest_asset is None:
                missing.append(MANIFEST_NAME)
            if sig_asset is None:
                missing.append(MANIFEST_SIGNATURE_NAME)
            if zip_asset is None:
                missing.append(ASSET_NAME)
            if missing:
                self.check_finished.emit(False, release_tag, "")
                self.error_occurred.emit(
                    f"Release {release_tag} is missing required assets: {', '.join(missing)}"
                )
                return

            # Download and verify the manifest
            manifest_bytes = self._download_manifest(manifest_asset or {})
            sig_bytes = self._download_signature(sig_asset or {})

            _verify_manifest_signature(manifest_bytes, sig_bytes)
            logger.info("Manifest signature verified successfully.")

            manifest = _parse_verified_manifest(manifest_bytes)
            logger.info(
                "Verified manifest v%s (sha256=%s, size=%d)",
                manifest.version,
                manifest.sha256,
                manifest.size_bytes,
            )

            # Version comparison
            try:
                candidate_ver = parse_version(manifest.version)
                current_ver = parse_version(CURRENT_VERSION)
            except Exception as exc:
                self.error_occurred.emit(f"Version parse error: {exc}")
                return

            if candidate_ver <= current_ver:
                logger.info("System is up to date (%s).", CURRENT_VERSION)
                self.check_finished.emit(False, CURRENT_VERSION, "")
                return

            # Rollback guard
            _validate_not_rollback(manifest.version)

            # Build the update context and store it for the download phase
            zip_url = zip_asset["browser_download_url"] if zip_asset else ""
            context = UpdateDownloadContext(
                manifest=manifest,
                zip_url=zip_url,
                release_tag=release_tag,
            )
            _pending_update_context = context

            logger.info("Update available: %s", manifest.version)
            self.check_finished.emit(True, manifest.version, zip_url)

        except requests.RequestException as exc:
            logger.error("Network error during update check: %s", exc)
            self.error_occurred.emit(f"Network error: {exc}")
        except ValueError as exc:
            logger.error("Manifest validation failed: %s", exc)
            self.error_occurred.emit(f"Update verification failed: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error during update check.")
            self.error_occurred.emit(f"Error checking updates: {exc}")

    # ------------------------------------------------------------------
    # Download update
    # ------------------------------------------------------------------

    def download_update(self, url: str) -> None:
        """Download the ZIP artifact and verify it against the signed manifest.

        The *url* parameter is kept for backward compatibility with the
        existing signal wiring; the SHA-256 and size expectations are read
        from the module-level ``_pending_update_context``.
        """
        global _pending_update_context, _verified_zip_paths

        context = _pending_update_context
        if context is None:
            self.error_occurred.emit(
                "No pending update context. Run check_updates() first."
            )
            return

        logger.info("Downloading update from: %s", context.zip_url)

        try:
            session_dir = _new_update_session_dir()
            zip_path = session_dir / ASSET_NAME

            with requests.get(
                context.zip_url, headers=self.headers, stream=True, timeout=30
            ) as r:
                r.raise_for_status()

                # Content-Length check (best-effort)
                content_length = r.headers.get("content-length")
                if content_length is not None:
                    try:
                        cl = int(content_length)
                        if cl != context.manifest.size_bytes:
                            self.download_finished.emit(
                                False,
                                f"Content-Length {cl} does not match "
                                f"manifest size {context.manifest.size_bytes}.",
                            )
                            return
                    except ValueError:
                        pass  # Non-integer Content-Length; skip

                total_size = context.manifest.size_bytes
                downloaded = 0

                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 100)
                                self.download_progress.emit(pct)

            # Post-download size check
            actual_size = zip_path.stat().st_size
            if actual_size != context.manifest.size_bytes:
                self.download_finished.emit(
                    False,
                    f"Downloaded file size {actual_size} does not match "
                    f"manifest size {context.manifest.size_bytes}.",
                )
                return

            # SHA-256 verification
            actual_sha256 = _compute_sha256(zip_path)
            if actual_sha256 != context.manifest.sha256.lower():
                self.download_finished.emit(
                    False,
                    f"SHA-256 mismatch.\n"
                    f"  Expected: {context.manifest.sha256}\n"
                    f"  Actual:   {actual_sha256}",
                )
                return

            # Mark as verified
            _verified_zip_paths.add(zip_path)
            logger.info(
                "Download complete and verified (SHA-256: %s).", actual_sha256
            )
            self.download_finished.emit(True, str(zip_path))

        except requests.RequestException as exc:
            logger.error("Download failed: %s", exc)
            self.download_finished.emit(False, f"Download failed: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error during download.")
            self.download_finished.emit(False, f"Download error: {exc}")

    # ------------------------------------------------------------------
    # Extract update
    # ------------------------------------------------------------------

    def extract_update(self, zip_path_str: str) -> None:
        """Extract a verified ZIP.  Refuses to extract unverified archives."""
        global _verified_zip_paths
        zip_path = Path(zip_path_str)

        if zip_path not in _verified_zip_paths:
            raise ValueError(
                f"ZIP has not been cryptographically verified: {zip_path}. "
                f"Refusing to extract."
            )

        try:
            temp_extract_dir = zip_path.parent / "extracted"

            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            temp_extract_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Extracting to %s", temp_extract_dir)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                _safe_extract_zip(zip_ref, temp_extract_dir, self.extraction_progress.emit)

            # Write verification metadata next to the extracted payload
            context = _pending_update_context
            metadata = {
                "verified_by": "PmGen Secure Updater",
                "manifest_version": context.manifest.version if context else "unknown",
                "sha256": context.manifest.sha256 if context else "unknown",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
            metadata_path = temp_extract_dir / ".pmgen_verified_update.json"
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

            self.extraction_finished.emit(str(zip_path), str(temp_extract_dir))

        except Exception as exc:
            logger.error("Extraction failed: %s", exc)
            self.error_occurred.emit(f"Extraction failed: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_latest_release(self) -> dict:
        """Return the parsed JSON of the latest GitHub release."""
        response = requests.get(
            GITHUB_API_LATEST, headers=self.headers, timeout=10
        )
        response.raise_for_status()
        return response.json()

    def _download_manifest(self, asset: dict) -> bytes:
        """Download the manifest JSON asset."""
        url = asset["browser_download_url"]
        logger.info("Downloading manifest: %s", url)
        return _download_bytes(url, self.headers)

    def _download_signature(self, asset: dict) -> bytes:
        """Download the manifest signature asset."""
        url = asset["browser_download_url"]
        logger.info("Downloading manifest signature: %s", url)
        return _download_bytes(url, self.headers)


# ---------------------------------------------------------------------------
# Helpers shared with UpdateWorker
# ---------------------------------------------------------------------------


def _find_asset(release: dict, name: str) -> dict | None:
    """Return the asset dict with *name* from a GitHub release, or None."""
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    return None


# ---------------------------------------------------------------------------
# Restart / apply update
# ---------------------------------------------------------------------------


def perform_restart(zip_path_str: str, temp_extract_dir_str: str) -> bool:
    """Terminate the current app and launch the external updater executable.

    Returns ``False`` if the restart could not be initiated (caller should
    inform the user); does **not** return at all on success (the process
    exits).

    Requires the ZIP to have been cryptographically verified before calling.
    """
    global _verified_zip_paths

    zip_path = Path(zip_path_str)
    if zip_path not in _verified_zip_paths:
        raise RuntimeError(
            "No verified update to install. The ZIP must be downloaded and "
            "verified through the secure updater before restart."
        )

    if not getattr(sys, "frozen", False):
        logging.warning("Application is not frozen. Skipping restart/update logic.")
        return False

    current_exe = Path(sys.executable)
    current_dir = current_exe.parent
    exe_name = current_exe.name

    # Pre-flight: verify the install directory is writable BEFORE exiting the app.
    try:
        probe = current_dir / f".pmgen_write_test_{uuid.uuid4().hex}"
        probe.touch()
        probe.unlink()
    except OSError as e:
        logging.critical(
            "Install directory is not writable: %s (%s). Aborting update restart.",
            current_dir,
            e,
        )
        return False

    # Prefer an updater shipped in the extracted update payload.
    temp_extract_dir = Path(temp_extract_dir_str)
    updater_source = _find_updater_exe_in_tree(temp_extract_dir)
    if updater_source is None:
        updater_source = current_dir / UPDATER_EXE_NAME
        if not updater_source.exists():
            logging.critical(
                "Updater executable not found in update payload or install directory. "
                "Looked in: %s and %s",
                temp_extract_dir,
                current_dir,
            )
            return False

    # Stage updater to temp before launching.
    staged_updater = _stage_updater_exe(updater_source)
    if staged_updater is None or not staged_updater.exists():
        logging.critical("Failed to stage updater executable; aborting update restart.")
        return False

    try:
        if zip_path.exists():
            zip_path.unlink()
    except OSError as e:
        logging.warning("Could not delete temp zip: %s", e)

    # Persist the installed version so rollback protection is active on the
    # next update check.  Read the manifest version from the metadata file
    # written during extract_update(); fall back to the pending context.
    version_to_save: str | None = None
    metadata_path = temp_extract_dir / ".pmgen_verified_update.json"
    try:
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            version_to_save = metadata.get("manifest_version")
    except (json.JSONDecodeError, OSError):
        pass

    if version_to_save is None and _pending_update_context is not None:
        version_to_save = _pending_update_context.manifest.version

    if version_to_save:
        try:
            _save_last_installed_version(version_to_save)
            logging.info("Saved last installed version: %s", version_to_save)
        except Exception:
            logging.exception("Failed to persist last installed version")
    else:
        logging.warning(
            "Could not determine manifest version; rollback protection skipped."
        )

    logging.info("Launching external updater and exiting...")

    session_id = Path(temp_extract_dir_str).parent.name

    subprocess.Popen(
        [
            str(staged_updater),
            temp_extract_dir_str,
            str(current_dir),
            exe_name,
            str(os.getpid()),
            session_id,
        ],
        cwd=str(current_dir),
    )

    sys.exit(0)