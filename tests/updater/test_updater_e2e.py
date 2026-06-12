"""End-to-end mock integration tests for the PmGen secure updater.

Simulates the full update flow: check -> download -> verify -> extract.
All tests use mocked GitHub API / file downloads, real Ed25519 keypairs,
and real test ZIP files.  Qt thread event loop is bypassed — methods are
called synchronously.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pmgen.updater import updater


# ---------------------------------------------------------------------------
# Autouse fixture: reset module-level state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_updater_globals() -> None:
    """Reset _pending_update_context and _verified_zip_paths before each test."""
    updater._pending_update_context = None
    updater._verified_zip_paths = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign_manifest(
    manifest: dict, private_key: Ed25519PrivateKey
) -> bytes:
    """Sign *manifest* JSON dict with *private_key* and return base64-encoded sig."""
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    signature = private_key.sign(manifest_bytes)
    return base64.b64encode(signature)


def _build_test_zip(tmp_path: Path) -> Path:
    """Create a small ZIP with dummy app files and return its path."""
    zip_path = tmp_path / "PmGen.zip"
    app_dir = tmp_path / "app_contents"
    app_dir.mkdir()
    (app_dir / "PmGen.exe").write_text("dummy exe")
    internal = app_dir / "_internal"
    internal.mkdir()
    (internal / "python.exe").write_text("dummy python")
    (app_dir / "updater.exe").write_text("dummy updater")

    with __import__("zipfile").ZipFile(zip_path, "w", __import__("zipfile").ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(app_dir):
            for file in files:
                full = Path(root) / file
                arcname = full.relative_to(app_dir)
                zf.write(full, arcname)
    return zip_path


def _fingerprint_zip(zip_path: Path) -> tuple[str, int]:
    """Return (sha256_hex, size_bytes) for a ZIP file."""
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    size = zip_path.stat().st_size
    return sha256, size


def _build_mock_github_release(
    manifest: dict,
    signature_b64: bytes,
    zip_path: Path,
    *,
    base_url: str = "https://github.com/test/repo/releases/download/v2.9.0",
    include_manifest: bool = True,
    include_signature: bool = True,
    include_zip: bool = True,
) -> dict:
    """Build a GitHub release JSON dict with the specified assets."""
    assets = []
    if include_manifest:
        assets.append({
            "name": "manifest.json",
            "browser_download_url": f"{base_url}/manifest.json",
        })
    if include_signature:
        assets.append({
            "name": "manifest.json.sig",
            "browser_download_url": f"{base_url}/manifest.json.sig",
        })
    if include_zip:
        assets.append({
            "name": "PmGen.zip",
            "browser_download_url": f"{base_url}/PmGen.zip",
        })

    return {
        "tag_name": "v2.9.0",
        "assets": assets,
        "_test_manifest": manifest,
        "_test_signature_b64": signature_b64,
        "_test_zip_path": zip_path,
    }


def _make_mock_get(release: dict) -> MagicMock:
    """Create a mock for ``requests.get`` that routes by URL pattern."""

    manifest_json = json.dumps(release["_test_manifest"], indent=2).encode("utf-8")
    signature_b64_bytes = release["_test_signature_b64"]
    zip_bytes = release["_test_zip_path"].read_bytes()

    def mock_get(url, **kwargs):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        if "api.github.com/repos" in url and "/releases" in url:
            # GitHub API
            resp.json.return_value = {
                k: v for k, v in release.items()
                if not k.startswith("_test_")
            }
            return resp

        if url.endswith("manifest.json.sig"):
            resp.content = signature_b64_bytes
            return resp

        if url.endswith("manifest.json"):
            resp.content = manifest_json
            return resp

        if url.endswith("PmGen.zip") or "PmGen.zip" in url:
            stream = kwargs.get("stream", False)
            if stream:
                resp.headers = {"content-length": str(len(zip_bytes))}
                resp.raw = io.BytesIO(zip_bytes)

                chunks = []
                remaining = zip_bytes
                while remaining:
                    chunk = remaining[:8192]
                    chunks.append(chunk)
                    remaining = remaining[8192:]

                resp.iter_content = MagicMock(return_value=iter(chunks))
                resp.__enter__ = MagicMock(return_value=resp)
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            else:
                resp.content = zip_bytes
                return resp

        # Unknown URL
        resp.status_code = 404
        resp.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("404 Not Found")
        )
        return resp

    return MagicMock(side_effect=mock_get)


def _connect_signal_collector(worker: "updater.UpdateWorker") -> dict:
    """Connect all signals to a results dict and return it."""
    results: dict = {}

    worker.check_finished.connect(
        lambda available, version, url: results.update(
            {"check_available": available, "check_version": version, "check_url": url}
        )
    )
    worker.download_progress.connect(
        lambda pct: results.setdefault("download_progress", []).append(pct)
    )
    worker.download_finished.connect(
        lambda success, path: results.update(
            {"download_success": success, "download_path": path}
        )
    )
    worker.extraction_progress.connect(
        lambda pct: results.setdefault("extraction_progress", []).append(pct)
    )
    worker.extraction_finished.connect(
        lambda zip_path, extract_dir: results.update(
            {"extraction_zip_path": zip_path, "extraction_dir": extract_dir}
        )
    )
    worker.error_occurred.connect(
        lambda msg: results.setdefault("errors", []).append(msg)
    )

    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def keypair() -> tuple:
    """Generate an Ed25519 keypair for signing test manifests.

    Returns (private_key, public_key, public_b64, private_b64).
    """
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    public_b64 = base64.b64encode(
        public.public_bytes_raw()
    ).decode("ascii")
    private_b64 = base64.b64encode(
        private.private_bytes_raw()
    ).decode("ascii")
    return private, public, public_b64, private_b64


@pytest.fixture
def test_zip(tmp_path: Path) -> Path:
    """A small real ZIP file with dummy app contents."""
    return _build_test_zip(tmp_path)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestUpdateFlowE2E:
    """End-to-end mock update flow: manifest -> signature -> download -> verify -> extract."""

    @staticmethod
    def _connect_and_run_check(worker: "updater.UpdateWorker", results: dict) -> None:
        """Run check_updates() and collect signal results."""
        worker.check_updates()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_full_update_flow_success(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Full E2E: check -> download -> verify -> extract."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(manifest, signature_b64, test_zip)

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            # Phase 1: Check for updates
            worker.check_updates()

            assert results["check_available"] is True
            assert results["check_version"] == "2.9.0"
            assert "PmGen.zip" in results["check_url"]

            # Phase 2: Download the update
            worker.download_update(results["check_url"])

            assert results["download_success"] is True
            assert Path(results["download_path"]).exists()

            # Phase 3: Verify SHA-256 independently
            actual_sha = updater._compute_sha256(results["download_path"])
            assert actual_sha == sha256

            # Phase 4: Extract
            worker.extract_update(results["download_path"])

            assert "extraction_dir" in results
            extract_dir = Path(results["extraction_dir"])
            assert extract_dir.exists()

            # Phase 5: Verify extracted payload
            all_files = list(extract_dir.rglob("*"))
            assert any("PmGen.exe" in str(p) for p in all_files)
            assert any("_internal" in str(p) for p in all_files)

            # Phase 6: Verify metadata file was written
            verified_meta = extract_dir / ".pmgen_verified_update.json"
            assert verified_meta.exists()
            meta = json.loads(verified_meta.read_text())
            assert meta["manifest_version"] == "2.9.0"

    # ------------------------------------------------------------------
    # Tampered ZIP — SHA-256 mismatch
    # ------------------------------------------------------------------

    def test_tampered_zip_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Modify ZIP bytes after manifest signing -> SHA-256 mismatch."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        # Tamper: replace bytes in-place to keep size identical but change SHA-256
        original = bytearray(test_zip.read_bytes())
        # Flip a byte near the end (ZIP central directory won't break extraction test)
        original[-10] = (original[-10] + 1) % 256
        tampered_zip = tmp_path / "PmGen_tampered.zip"
        tampered_zip.write_bytes(bytes(original))

        # Release still points to the tampered ZIP, but manifest has original SHA-256
        release = _build_mock_github_release(manifest, signature_b64, test_zip)
        release["_test_zip_path"] = tampered_zip

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()
            assert results["check_available"] is True

            worker.download_update(results["check_url"])
            assert results["download_success"] is False
            assert "SHA-256 mismatch" in results["download_path"]

    # ------------------------------------------------------------------
    # Tampered manifest — signature verification fails
    # ------------------------------------------------------------------

    def test_tampered_manifest_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Modify manifest JSON after signing -> signature verification fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        # Tamper the manifest after signing
        tampered_manifest = dict(manifest)
        tampered_manifest["version"] = "9.9.9"

        release = _build_mock_github_release(manifest, signature_b64, test_zip)
        release["_test_manifest"] = tampered_manifest  # different from signed bytes

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert "errors" in results
            assert any(
                "signature" in err.lower() for err in results["errors"]
            ), f"Expected signature error, got: {results['errors']}"

    # ------------------------------------------------------------------
    # Missing manifest asset
    # ------------------------------------------------------------------

    def test_missing_manifest_asset_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Release has ZIP but no manifest.json -> check_updates fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(
            manifest, signature_b64, test_zip, include_manifest=False
        )

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert results["check_available"] is False
            assert "errors" in results
            assert any(
                "manifest.json" in err for err in results["errors"]
            )

    # ------------------------------------------------------------------
    # Missing signature asset
    # ------------------------------------------------------------------

    def test_missing_signature_asset_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Release has manifest.json but no .sig -> check_updates fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(
            manifest, signature_b64, test_zip, include_signature=False
        )

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert results["check_available"] is False
            assert "errors" in results
            assert any(
                "manifest.json.sig" in err for err in results["errors"]
            )

    # ------------------------------------------------------------------
    # No newer version
    # ------------------------------------------------------------------

    def test_no_newer_version_reported(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Manifest version == CURRENT_VERSION -> check_updates reports no update."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(manifest, signature_b64, test_zip)

        # CURRENT_VERSION matches manifest version
        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.9.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert results["check_available"] is False
            assert results["check_version"] == "2.9.0"
            assert results["check_url"] == ""

    # ------------------------------------------------------------------
    # Downgrade rejected
    # ------------------------------------------------------------------

    def test_downgrade_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Manifest version < last installed -> check_updates fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(manifest, signature_b64, test_zip)

        # Pre-populate state file with a version HIGHER than manifest
        state_file = tmp_path / "update_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_installed_version": "3.0.0"})
        )

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", state_file), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert "errors" in results
            assert any(
                "rollback" in err.lower() for err in results["errors"]
            ), f"Expected rollback error, got: {results['errors']}"

    # ------------------------------------------------------------------
    # Content-Length mismatch
    # ------------------------------------------------------------------

    def test_content_length_mismatch_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Content-Length header differs from manifest.size_bytes -> download fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,  # real size
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(manifest, signature_b64, test_zip)

        # Build a custom mock that returns a wrong Content-Length
        mock_get = _make_mock_get(release)

        # Wrap to inject wrong Content-Length for the ZIP URL
        original_side_effect = mock_get.side_effect

        def inject_bad_content_length(url, **kwargs):
            resp = original_side_effect(url, **kwargs)
            if "PmGen.zip" in url and kwargs.get("stream"):
                resp.headers = {"content-length": str(size + 99999)}
            return resp

        mock_get.side_effect = inject_bad_content_length

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", mock_get):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()
            assert results["check_available"] is True

            worker.download_update(results["check_url"])
            assert results["download_success"] is False
            assert "Content-Length" in results["download_path"]

    # ------------------------------------------------------------------
    # Wrong public key
    # ------------------------------------------------------------------

    def test_wrong_public_key_rejected(
        self, qtbot, keypair, test_zip, tmp_path
    ) -> None:
        """Manifest signed with key A, verify with key B -> signature fails."""
        _private, _public, public_b64, _private_b64 = keypair
        sha256, size = _fingerprint_zip(test_zip)

        manifest = {
            "schema_version": 1,
            "app_id": "PmGen",
            "version": "2.9.0",
            "asset_name": "PmGen.zip",
            "sha256": sha256,
            "size_bytes": size,
            "release_date": "2026-06-12",
            "signature_algorithm": "ed25519",
        }
        signature_b64 = _sign_manifest(manifest, keypair[0])

        release = _build_mock_github_release(manifest, signature_b64, test_zip)

        # Generate a DIFFERENT keypair for the "expected" public key
        wrong_private = Ed25519PrivateKey.generate()
        wrong_public = wrong_private.public_key()
        wrong_public_b64 = base64.b64encode(
            wrong_public.public_bytes_raw()
        ).decode("ascii")

        with patch("pmgen.updater.updater.SIGNING_PUBLIC_KEY_B64", wrong_public_b64), \
             patch("pmgen.updater.updater.CURRENT_VERSION", "2.8.0"), \
             patch("pmgen.updater.updater.UPDATE_STATE_FILE", tmp_path / "update_state.json"), \
             patch("pmgen.updater.updater.GITHUB_API_LATEST", "https://api.github.com/repos/test/repo/releases/latest"), \
             patch("requests.get", _make_mock_get(release)):

            worker = updater.UpdateWorker()
            results = _connect_signal_collector(worker)

            worker.check_updates()

            assert "errors" in results
            assert any(
                "signature" in err.lower() for err in results["errors"]
            ), f"Expected signature error with wrong key, got: {results['errors']}"
