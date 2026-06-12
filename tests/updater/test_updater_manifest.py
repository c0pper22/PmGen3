"""Unit tests for PmGen secure updater — manifest parsing, signature
verification, rollback protection, SHA-256, download helpers, and asset
finding.

These tests exercise pure-logic functions from ``pmgen.updater.updater``
and do **not** depend on Qt.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pmgen.updater import updater
from pmgen.updater.updater import (
    VerifiedUpdateManifest,
    _compute_sha256,
    _download_bytes,
    _find_asset,
    _load_last_installed_version,
    _load_public_key,
    _parse_verified_manifest,
    _save_last_installed_version,
    _validate_not_rollback,
    _verify_manifest_signature,
)


# ============================================================================
# Test helpers
# ============================================================================


def _make_valid_manifest_bytes(**overrides) -> bytes:
    """Create valid manifest JSON bytes with optional field overrides."""
    manifest: dict = {
        "schema_version": 1,
        "app_id": "PmGen",
        "version": "2.9.0",
        "asset_name": "PmGen.zip",
        "sha256": "a" * 64,
        "size_bytes": 12345678,
        "signature_algorithm": "ed25519",
    }
    manifest.update(overrides)
    return json.dumps(manifest).encode("utf-8")


# ============================================================================
# Manifest parsing
# ============================================================================


class TestParseVerifiedManifest:
    """Tests for ``_parse_verified_manifest``."""

    def test_valid_manifest_parses_correctly(self) -> None:
        """All required fields present → returns VerifiedUpdateManifest."""
        result = _parse_verified_manifest(_make_valid_manifest_bytes())
        assert isinstance(result, VerifiedUpdateManifest)
        assert result.version == "2.9.0"
        assert result.asset_name == "PmGen.zip"
        assert result.sha256 == "a" * 64
        assert result.size_bytes == 12345678
        assert result.release_date is None
        assert result.minimum_supported_version is None

    def test_missing_schema_version_raises(self) -> None:
        data = _make_valid_manifest_bytes()
        parsed = json.loads(data)
        del parsed["schema_version"]
        with pytest.raises(ValueError, match="schema_version"):
            _parse_verified_manifest(json.dumps(parsed).encode("utf-8"))

    def test_wrong_schema_version_raises(self) -> None:
        with pytest.raises(ValueError, match="schema_version"):
            _parse_verified_manifest(_make_valid_manifest_bytes(schema_version=2))

    def test_wrong_app_id_raises(self) -> None:
        with pytest.raises(ValueError, match="app_id"):
            _parse_verified_manifest(_make_valid_manifest_bytes(app_id="OtherApp"))

    def test_wrong_signature_algorithm_raises(self) -> None:
        with pytest.raises(ValueError, match="signature_algorithm"):
            _parse_verified_manifest(
                _make_valid_manifest_bytes(signature_algorithm="rsa")
            )

    def test_wrong_asset_name_raises(self) -> None:
        with pytest.raises(ValueError, match="asset_name"):
            _parse_verified_manifest(
                _make_valid_manifest_bytes(asset_name="OtherApp.zip")
            )

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValueError, match="version"):
            _parse_verified_manifest(_make_valid_manifest_bytes(version=""))

    def test_sha256_wrong_length_raises(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            _parse_verified_manifest(_make_valid_manifest_bytes(sha256="abc123"))

    def test_sha256_non_hex_raises(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            _parse_verified_manifest(
                _make_valid_manifest_bytes(sha256="g" * 64)
            )

    def test_size_bytes_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="size_bytes"):
            _parse_verified_manifest(_make_valid_manifest_bytes(size_bytes=0))

    def test_size_bytes_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="size_bytes"):
            _parse_verified_manifest(_make_valid_manifest_bytes(size_bytes=-1))

    def test_size_bytes_missing_raises(self) -> None:
        data = _make_valid_manifest_bytes()
        parsed = json.loads(data)
        del parsed["size_bytes"]
        with pytest.raises(ValueError, match="size_bytes"):
            _parse_verified_manifest(json.dumps(parsed).encode("utf-8"))

    def test_size_bytes_not_int_raises(self) -> None:
        with pytest.raises(ValueError, match="size_bytes"):
            _parse_verified_manifest(
                _make_valid_manifest_bytes(size_bytes="large")
            )

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_verified_manifest(b"not valid json {{{")

    def test_minimum_supported_version_blocks_old_app(self) -> None:
        """When CURRENT_VERSION < minimum_supported_version, reject."""
        with patch.object(updater, "CURRENT_VERSION", "2.0.0"):
            with pytest.raises(ValueError, match="Update requires version"):
                _parse_verified_manifest(
                    _make_valid_manifest_bytes(minimum_supported_version="2.9.0")
                )

    def test_minimum_supported_version_allows_newer_app(self) -> None:
        """When CURRENT_VERSION >= minimum_supported_version, accept."""
        with patch.object(updater, "CURRENT_VERSION", "3.0.0"):
            result = _parse_verified_manifest(
                _make_valid_manifest_bytes(minimum_supported_version="2.9.0")
            )
            assert result.minimum_supported_version == "2.9.0"

    def test_optional_fields_preserved(self) -> None:
        """release_date and minimum_supported_version stored if present."""
        result = _parse_verified_manifest(
            _make_valid_manifest_bytes(
                release_date="2025-06-01",
                minimum_supported_version="2.8.0",
            )
        )
        assert result.release_date == "2025-06-01"
        assert result.minimum_supported_version == "2.8.0"

    def test_sha256_uppercase_is_accepted_and_lowered(self) -> None:
        """Uppercase hex sha256 is accepted and normalized to lowercase."""
        upper_sha = "A" * 32 + "B" * 32
        result = _parse_verified_manifest(
            _make_valid_manifest_bytes(sha256=upper_sha)
        )
        assert result.sha256 == upper_sha.lower()


# ============================================================================
# Signature verification
# ============================================================================


class TestSignatureVerification:
    """Tests for ``_verify_manifest_signature`` and ``_load_public_key``."""

    @pytest.fixture
    def keypair(self) -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
        """Generate a fresh Ed25519 keypair for each test.

        Returns (private_key, public_key, public_b64) where public_b64
        is the base64-encoded raw public key bytes (as used by the
        updater's SIGNING_PUBLIC_KEY_B64).
        """
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        public_b64 = base64.b64encode(
            public.public_bytes_raw()
        ).decode("ascii")
        return private, public, public_b64

    def _sign_manifest(
        self, private_key: Ed25519PrivateKey, manifest_bytes: bytes
    ) -> bytes:
        """Sign *manifest_bytes* and return the contents of the .sig file.

        Matches what build_sign_zip.py writes to manifest.json.sig:
        base64-encoded signature as ASCII bytes.
        """
        signature = private_key.sign(manifest_bytes)
        return base64.b64encode(signature)

    def test_valid_signature_passes(self, keypair) -> None:
        """Sign manifest with private key, verify with public key → passes."""
        private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()
        sig_bytes = self._sign_manifest(private, manifest_bytes)

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            # Should not raise
            _verify_manifest_signature(manifest_bytes, sig_bytes)

    def test_tampered_manifest_fails(self, keypair) -> None:
        """Modify manifest bytes after signing → verification fails."""
        private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()
        sig_bytes = self._sign_manifest(private, manifest_bytes)

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            with pytest.raises(ValueError, match="signature verification failed"):
                _verify_manifest_signature(
                    b"tampered manifest content", sig_bytes
                )

    def test_wrong_public_key_fails(self, keypair) -> None:
        """Verify with different keypair's public key → fails."""
        private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()
        sig_bytes = self._sign_manifest(private, manifest_bytes)

        # Generate a different keypair for the "wrong" public key
        other_private = Ed25519PrivateKey.generate()
        other_public_b64 = base64.b64encode(
            other_private.public_key().public_bytes_raw()
        ).decode("ascii")

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", other_public_b64):
            with pytest.raises(ValueError, match="signature verification failed"):
                _verify_manifest_signature(manifest_bytes, sig_bytes)

    def test_garbage_signature_bytes_fails(self, keypair) -> None:
        """Random bytes as signature → fails."""
        _private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            with pytest.raises(ValueError, match="signature verification"):
                _verify_manifest_signature(manifest_bytes, b"not-a-signature!!!")

    def test_invalid_signature_length_fails(self, keypair) -> None:
        """Base64 that decodes to wrong number of bytes → fails."""
        _private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()
        # Valid base64 but decodes to 4 bytes (not 64)
        bad_sig = base64.b64encode(b"\x00\x01\x02\x03")

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            with pytest.raises(ValueError, match="signature verification"):
                _verify_manifest_signature(manifest_bytes, bad_sig)

    def test_load_public_key_valid_base64(self, keypair) -> None:
        """Valid base64 Ed25519 public key loads correctly."""
        _private, public, public_b64 = keypair
        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            key = _load_public_key()
            assert isinstance(key, Ed25519PublicKey)
            assert key.public_bytes_raw() == public.public_bytes_raw()

    def test_load_public_key_invalid_base64_raises(self) -> None:
        """Non-base64 string raises error."""
        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", "!!!not-base64!!!"):
            with pytest.raises(Exception):
                _load_public_key()

    def test_load_public_key_wrong_key_type_raises(self) -> None:
        """Valid base64 but wrong length for Ed25519 public key raises."""
        # Ed25519 public keys are 32 bytes — 31 bytes is invalid
        fake_key_b64 = base64.b64encode(b"\x00" * 31).decode("ascii")
        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", fake_key_b64):
            with pytest.raises(Exception):
                _load_public_key()

    def test_signature_with_surrounding_whitespace(self, keypair) -> None:
        """Whitespace around base64 signature is stripped."""
        private, _public, public_b64 = keypair
        manifest_bytes = _make_valid_manifest_bytes()
        # Build sig with surrounding newlines (like a hand-edited .sig file)
        raw_sig = base64.b64encode(private.sign(manifest_bytes))
        sig_bytes = b"  \n" + raw_sig + b"\n  "

        with patch.object(updater, "SIGNING_PUBLIC_KEY_B64", public_b64):
            # Should not raise
            _verify_manifest_signature(manifest_bytes, sig_bytes)


# ============================================================================
# Rollback / version protection
# ============================================================================


class TestRollbackProtection:
    """Tests for ``_validate_not_rollback``, ``_save_last_installed_version``,
    and ``_load_last_installed_version``."""

    @pytest.fixture(autouse=True)
    def clean_state(self, tmp_path: Path, monkeypatch) -> None:
        """Redirect UPDATE_STATE_FILE to a temp path."""
        state_file = tmp_path / "update_state.json"
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)

    def test_no_history_allows_any_version(self) -> None:
        """No state file → _validate_not_rollback passes for any version."""
        # Should not raise
        _validate_not_rollback("0.1.0")
        _validate_not_rollback("99.0.0")

    def test_rejects_downgrade(self) -> None:
        """Candidate < last installed → raises ValueError."""
        _save_last_installed_version("3.0.0")
        with pytest.raises(ValueError, match="rollback"):
            _validate_not_rollback("2.0.0")

    def test_allows_upgrade(self) -> None:
        """Candidate > last installed → passes."""
        _save_last_installed_version("2.0.0")
        # Should not raise
        _validate_not_rollback("3.0.0")

    def test_allows_same_version(self) -> None:
        """Candidate == last installed → passes (re-install allowed)."""
        _save_last_installed_version("2.9.0")
        # Should not raise
        _validate_not_rollback("2.9.0")

    def test_save_and_load_roundtrip(self) -> None:
        """Save version, load it back → same value."""
        _save_last_installed_version("3.1.4")
        loaded = _load_last_installed_version()
        assert loaded == "3.1.4"

    def test_load_no_file_returns_none(self) -> None:
        """No state file → _load_last_installed_version returns None."""
        assert _load_last_installed_version() is None

    def test_load_corrupted_json_returns_none(self, monkeypatch, tmp_path) -> None:
        """Corrupted JSON file → returns None."""
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("not json at all", encoding="utf-8")
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)
        assert _load_last_installed_version() is None

    def test_load_non_dict_returns_none(self, monkeypatch, tmp_path) -> None:
        """JSON file that is not a dict → returns None."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)
        assert _load_last_installed_version() is None

    def test_load_missing_version_key_returns_none(self, monkeypatch, tmp_path) -> None:
        """State file without 'last_installed_version' → returns None."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({"other": "data"}), encoding="utf-8"
        )
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)
        assert _load_last_installed_version() is None

    def test_load_empty_version_string_returns_none(
        self, monkeypatch, tmp_path
    ) -> None:
        """Version is empty string → returns None."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({"last_installed_version": ""}), encoding="utf-8"
        )
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)
        assert _load_last_installed_version() is None

    def test_save_creates_parent_directories(self, monkeypatch, tmp_path) -> None:
        """Saving creates parent directories if needed."""
        state_file = tmp_path / "deeply" / "nested" / "state.json"
        monkeypatch.setattr(updater, "UPDATE_STATE_FILE", state_file)
        _save_last_installed_version("1.0.0")
        assert state_file.exists()
        loaded = _load_last_installed_version()
        assert loaded == "1.0.0"


# ============================================================================
# SHA-256 & download helpers
# ============================================================================


class TestSha256Helpers:
    """Tests for ``_compute_sha256``."""

    SHA256_EMPTY = (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )

    def test_compute_sha256_known_content(self, tmp_path: Path) -> None:
        """SHA-256 of known content matches expected value."""
        file_path = tmp_path / "test.txt"
        content = b"Hello, PmGen updater!"
        file_path.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_sha256(file_path) == expected

    def test_compute_sha256_empty_file(self, tmp_path: Path) -> None:
        """SHA-256 of empty file is correct."""
        file_path = tmp_path / "empty.bin"
        file_path.write_bytes(b"")
        assert _compute_sha256(file_path) == self.SHA256_EMPTY

    def test_compute_sha256_different_content_different_hash(
        self, tmp_path: Path
    ) -> None:
        """Two different files produce different hashes."""
        file_a = tmp_path / "a.bin"
        file_b = tmp_path / "b.bin"
        file_a.write_bytes(b"alpha")
        file_b.write_bytes(b"beta")
        assert _compute_sha256(file_a) != _compute_sha256(file_b)

    def test_compute_sha256_large_file(self, tmp_path: Path) -> None:
        """SHA-256 of a file larger than the chunk size still works."""
        file_path = tmp_path / "large.bin"
        # 3 MiB — larger than the 1 MiB chunk size
        content = b"\x42" * (3 * 1024 * 1024)
        file_path.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_sha256(file_path) == expected


class TestDownloadBytes:
    """Tests for ``_download_bytes``."""

    def test_successful_download(self) -> None:
        """Mock requests.get → returns expected bytes."""
        expected = b"fake manifest content"
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.content = expected

        with patch.object(updater.requests, "get", return_value=mock_response) as mock_get:
            result = _download_bytes("https://example.com/manifest.json", {})
            assert result == expected
            mock_get.assert_called_once_with(
                "https://example.com/manifest.json",
                headers={},
                timeout=10,
            )

    def test_http_error_raises(self) -> None:
        """Non-200 status → raises HTTPError."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch.object(updater.requests, "get", return_value=mock_response):
            with pytest.raises(requests.HTTPError, match="404"):
                _download_bytes("https://example.com/bad.json", {})


class TestFindAsset:
    """Tests for ``_find_asset``."""

    RELEASE: dict = {
        "tag_name": "v2.9.0",
        "assets": [
            {"name": "PmGen.zip", "browser_download_url": "https://example.com/PmGen.zip"},
            {"name": "manifest.json", "browser_download_url": "https://example.com/manifest.json"},
            {"name": "manifest.json.sig", "browser_download_url": "https://example.com/manifest.json.sig"},
        ],
    }

    def test_finds_asset_by_name(self) -> None:
        """Asset with matching name in release assets list → returns asset dict."""
        result = _find_asset(self.RELEASE, "PmGen.zip")
        assert result is not None
        assert result["name"] == "PmGen.zip"
        assert result["browser_download_url"] == "https://example.com/PmGen.zip"

    def test_returns_none_when_not_found(self) -> None:
        """No matching asset → returns None."""
        result = _find_asset(self.RELEASE, "does-not-exist.zip")
        assert result is None

    def test_returns_none_for_empty_assets(self) -> None:
        """Release with no assets → returns None."""
        release = {"tag_name": "v1.0", "assets": []}
        assert _find_asset(release, "PmGen.zip") is None

    def test_returns_none_for_missing_assets_key(self) -> None:
        """Release without 'assets' key → returns None."""
        release: dict = {"tag_name": "v1.0"}
        assert _find_asset(release, "PmGen.zip") is None  # type: ignore[arg-type]


# ============================================================================
# VerifiedUpdateManifest dataclass
# ============================================================================


class TestVerifiedUpdateManifest:
    """Tests for the ``VerifiedUpdateManifest`` dataclass."""

    def test_construction_with_required_fields(self) -> None:
        m = VerifiedUpdateManifest(
            version="2.9.0",
            asset_name="PmGen.zip",
            sha256="a" * 64,
            size_bytes=1000000,
        )
        assert m.version == "2.9.0"
        assert m.release_date is None
        assert m.minimum_supported_version is None

    def test_construction_with_all_fields(self) -> None:
        m = VerifiedUpdateManifest(
            version="2.9.0",
            asset_name="PmGen.zip",
            sha256="f" * 64,
            size_bytes=5000000,
            release_date="2025-06-01",
            minimum_supported_version="2.8.0",
        )
        assert m.release_date == "2025-06-01"
        assert m.minimum_supported_version == "2.8.0"

    def test_is_frozen(self) -> None:
        m = VerifiedUpdateManifest(
            version="2.9.0",
            asset_name="PmGen.zip",
            sha256="c" * 64,
            size_bytes=1,
        )
        with pytest.raises(Exception):
            m.version = "3.0.0"  # type: ignore[misc]
