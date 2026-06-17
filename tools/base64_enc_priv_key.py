#!/usr/bin/env python3
"""Extract the raw 32-byte Ed25519 seed from a PEM-encoded private key and
base64-encode it for use with build_sign_zip.py (PMGEN_SIGNING_KEY env var).

Usage:
  python base64_enc_priv_key.py signing_private.key
  python base64_enc_priv_key.py -o output.txt signing_private.key
"""

import sys
import base64
import argparse
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    NoEncryption,
    load_pem_private_key,
)

# Resolve repo root relative to this script's location
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = REPO_ROOT / "keys" / "signing_private.key"


def encode_private_key(pem_path: Path, password: bytes | None = None) -> str:
    """Load a PEM Ed25519 private key, extract raw 32 bytes, base64-encode.

    Args:
        pem_path: Path to the PEM file (PKCS#8 format).
        password: Password bytes for encrypted keys, or None.

    Returns:
        Base64-encoded raw 32-byte private key string.

    Raises:
        FileNotFoundError: If the PEM file does not exist.
        ValueError: If the file is not a valid PEM Ed25519 private key.
    """
    pem_data = pem_path.read_bytes()

    try:
        key = load_pem_private_key(pem_data, password=password)
    except TypeError:
        # cryptography raises TypeError for password-protected keys when
        # password=None. Re-raise with a clearer message.
        raise ValueError(
            "Private key is encrypted. Provide --password or --password-file."
        ) from None
    except Exception as exc:
        raise ValueError(f"Failed to load private key: {exc}") from exc

    try:
        raw = key.private_bytes(
            encoding=Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        )
    except Exception as exc:
        raise ValueError(
            f"Could not extract raw key bytes. Is this an Ed25519 key? {exc}"
        ) from exc

    return base64.b64encode(raw).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Base64-encode an Ed25519 PEM private key for PmGen signing."
    )
    parser.add_argument(
        "pem_file",
        nargs="?",
        default=str(DEFAULT_KEY_PATH),
        help="Path to PEM-encoded Ed25519 private key (default: keys/signing_private.key)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write base64 key to FILE instead of stdout.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational messages; print only the key.",
    )
    parser.add_argument(
        "--password",
        help="Password for encrypted PEM key (insecure; prefer --password-file).",
    )
    parser.add_argument(
        "--password-file",
        metavar="FILE",
        help="Read password from FILE (first line only).",
    )
    args = parser.parse_args()

    pem_path = Path(args.pem_file)

    if not pem_path.exists():
        print(f"Error: File not found: {pem_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve password
    password: bytes | None = None
    if args.password:
        password = args.password.encode("utf-8")
    elif args.password_file:
        pw_path = Path(args.password_file)
        if not pw_path.exists():
            print(f"Error: Password file not found: {pw_path}", file=sys.stderr)
            sys.exit(1)
        password = pw_path.read_bytes().split(b"\n")[0].rstrip(b"\r")

    try:
        encoded = encode_private_key(pem_path, password)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(encoded, encoding="ascii")
        if not args.quiet:
            print(f"Base64 key written to: {args.output}")
    else:
        if args.quiet:
            print(encoded)
        else:
            print(encoded)
            print()
            print("--- Set this value as PMGEN_SIGNING_KEY ---")
            print(f'  $env:PMGEN_SIGNING_KEY = "{encoded}"')
            print(f"  or: setx PMGEN_SIGNING_KEY \"{encoded}\"")


if __name__ == "__main__":
    main()