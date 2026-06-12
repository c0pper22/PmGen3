#!/usr/bin/env python3
"""Generate Ed25519 signing keypair for PmGen secure updater.

Outputs:
  signing_private.key  — PEM-encoded private key (store securely, NEVER commit)
  signing_public.key   — PEM-encoded public key

Also prints base64-encoded keys for:
  PMGEN_SIGNING_KEY environment variable (private)
  SIGNING_PUBLIC_KEY_B64 in pmgen/updater/updater.py (public)
"""

import sys
import base64
import argparse
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


def generate_keypair() -> tuple[Ed25519PrivateKey, object]:
    """Generate a fresh Ed25519 keypair."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    return private, public


def save_key_files(
    private_key: Ed25519PrivateKey,
    public_key: object,
    output_dir: str,
    force: bool = False,
) -> tuple[Path, Path]:
    """Save PEM-encoded key files, prompting before overwrite unless forced."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / "signing_private.key"
    public_path = out_dir / "signing_public.key"

    for path in (private_path, public_path):
        if path.exists() and not force:
            response = input(f"{path} already exists. Overwrite? [y/N]: ")
            if response.lower() != "y":
                print("Aborted.")
                sys.exit(1)

    private_path.write_bytes(
        private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
    )
    public_path.write_bytes(
        public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def main() -> None:
    """Generate Ed25519 signing keys and print usage instructions."""
    parser = argparse.ArgumentParser(
        description="Generate PmGen Ed25519 signing keys"
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing key files without prompt",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=".",
        help="Output directory (default: current directory)",
    )
    args = parser.parse_args()

    print("Generating Ed25519 keypair for PmGen secure updater...")
    private_key, public_key = generate_keypair()

    # Save PEM files
    priv_path, pub_path = save_key_files(
        private_key, public_key, args.output_dir, args.force
    )

    # Base64 encode for env var / updater.py
    private_b64 = base64.b64encode(private_key.private_bytes_raw()).decode()
    public_b64 = base64.b64encode(public_key.public_bytes_raw()).decode()

    print()
    print("=" * 60)
    print("  KEYS GENERATED SUCCESSFULLY")
    print("=" * 60)
    print()
    print(f"  Private key file: {priv_path.resolve()}")
    print(f"  Public key file:  {pub_path.resolve()}")
    print()
    print("  --- For build_sign_zip.py ---")
    print(f"  PMGEN_SIGNING_KEY={private_b64}")
    print()
    print("  --- For pmgen/updater/updater.py ---")
    print(f'  SIGNING_PUBLIC_KEY_B64 = "{public_b64}"')
    print()
    print("=" * 60)
    print()
    print("  ⚠️  NEVER commit signing_private.key to version control!")
    print("  ⚠️  Store it in a key vault or secure location.")
    print("  ✅ signing_public.key is safe to track in the repo.")


if __name__ == "__main__":
    main()
