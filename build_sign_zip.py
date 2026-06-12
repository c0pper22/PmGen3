import os
import subprocess
import getpass
import glob
import zipfile
import hashlib
import json
import datetime
import base64

# Ed25519 private key for manifest signing (base64-encoded 32 bytes)
# NEVER commit this value. Set as environment variable or read from secure location.
PRIVATE_KEY_B64 = os.environ.get("PMGEN_SIGNING_KEY", "")


def get_password(pfx_path):
    password = getpass.getpass(prompt=f"Enter password for {pfx_path}: ")
    return password.strip()


def build_from_spec(spec_file):
    """Runs PyInstaller using the provided .spec file."""
    print(f"--- Building from {spec_file} ---")
    try:
        subprocess.run(["pyinstaller", "--noconfirm", "--clean", spec_file], check=True)
    except subprocess.CalledProcessError:
        print("Build failed. Check your .spec file logic.")
        exit(1)


def find_signtool():
    """Locates the latest version of signtool.exe in the Windows SDK folders."""
    base_path = r"C:\Program Files (x86)\Windows Kits\10\bin"
    search_pattern = os.path.join(base_path, "**", "x64", "signtool.exe")
    files = glob.glob(search_pattern, recursive=True)

    if not files:
        raise FileNotFoundError("signtool.exe not found. Is the Windows SDK installed?")

    files.sort(reverse=True)
    return files[0]


def sign_binary(signtool, password, binary_path, pfx_path):
    """Signs a single binary file."""
    try:
        cmd = [
            signtool,
            "sign",
            "/as",
            "/f",
            pfx_path,
            "/p",
            password,
            "/fd",
            "sha256",
            "/tr",
            "http://timestamp.digicert.com",
            "/td",
            "sha256",
            "/q",
            binary_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"Successfully signed: {os.path.relpath(binary_path, 'dist')}")
        else:
            print(f"FAILED to sign {binary_path}:")
            print(result.stderr)

    except Exception as e:
        print(f"Error signing {binary_path}: {e}")


def zip_directory(folder_path, output_zip):
    """Zips the entire content of a folder into a single archive."""
    print(f"--- Creating Zip: {output_zip} ---")
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_full_path = os.path.join(root, file)
                arcname = os.path.relpath(file_full_path, start=folder_path)
                zipf.write(file_full_path, arcname)
    print(f"Package created: {os.path.abspath(output_zip)}")


def compute_sha256(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def create_manifest(zip_path, version, min_supported_version="2.8.0"):
    """Create manifest.json for the secure updater."""
    sha256 = compute_sha256(zip_path)
    size_bytes = os.path.getsize(zip_path)
    release_date = datetime.date.today().isoformat()

    manifest = {
        "schema_version": 1,
        "app_id": "PmGen",
        "version": version,
        "asset_name": "PmGen.zip",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "release_date": release_date,
        "minimum_supported_version": min_supported_version,
        "signature_algorithm": "ed25519",
    }

    manifest_path = os.path.join(FINAL_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest created: {os.path.abspath(manifest_path)}")
    return manifest_path


def sign_manifest(manifest_path, private_key_b64):
    """Sign manifest.json with Ed25519 private key, write manifest.json.sig."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # Read exact manifest bytes
    with open(manifest_path, "rb") as f:
        manifest_bytes = f.read()

    # Decode private key and sign
    private_key_bytes = base64.b64decode(private_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_key.sign(manifest_bytes)

    # Base64-encode signature
    sig_b64 = base64.b64encode(signature).decode("ascii")

    sig_path = os.path.join(FINAL_DIR, "manifest.json.sig")
    with open(sig_path, "w", encoding="ascii") as f:
        f.write(sig_b64)
    print(f"Signature created: {os.path.abspath(sig_path)}")
    return sig_path


def read_version_from_updater(updater_path):
    """Extract CURRENT_VERSION from updater.py."""
    with open(updater_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("CURRENT_VERSION"):
                # Parse: CURRENT_VERSION = "2.8.0"
                return line.split("=")[1].strip().strip('"').strip("'")
    raise ValueError(f"CURRENT_VERSION not found in {updater_path}")


FINAL_DIR = "final"

if __name__ == "__main__":
    DIST_DIR = "dist/PmGen"
    PFX_FILE = r"C:\Users\Copper\PMGEN_TEST_3_13_26\PmGen\helpers\IBSCert.pfx"
    SPEC_FILE = "pmgen.spec"
    ZIP_NAME = os.path.join(FINAL_DIR, "PmGen.zip")

    os.makedirs(FINAL_DIR, exist_ok=True)

    if not os.path.exists(PFX_FILE):
        print(f"Error: PFX file not found at {PFX_FILE}")
        exit(1)

    signtool_path = find_signtool()
    password = get_password(PFX_FILE)

    build_from_spec(SPEC_FILE)

    print("\n--- Starting Recursive Signing (EXEs, DLLs, PYDs) ---")
    if os.path.exists(DIST_DIR):
        extensions = ("*.exe", "*.dll", "*.pyd")
        files_to_sign = []
        for ext in extensions:
            files_to_sign.extend(
                glob.glob(os.path.join(DIST_DIR, "**", ext), recursive=True)
            )

        for file_path in files_to_sign:
            sign_binary(signtool_path, password, file_path, PFX_FILE)
    else:
        print(f"Error: Build directory {DIST_DIR} not found.")
        exit(1)

    zip_directory(DIST_DIR, ZIP_NAME)

    # Read version from updater.py
    version = read_version_from_updater("pmgen/updater/updater.py")
    print(f"App version: {version}")

    if not PRIVATE_KEY_B64:
        print("Error: PMGEN_SIGNING_KEY environment variable not set.")
        print("Set it to the base64-encoded Ed25519 private key (32 bytes).")
        print("Example: set PMGEN_SIGNING_KEY=your_base64_key_here")
        exit(1)

    # Create and sign manifest
    manifest_path = create_manifest(ZIP_NAME, version)
    sign_manifest(manifest_path, PRIVATE_KEY_B64)
    print("\nPipeline Complete!")

# To generate a new Ed25519 keypair for release signing:
#   python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; key = Ed25519PrivateKey.generate(); print(f'Private: {base64.b64encode(key.private_bytes_raw()).decode()}'); print(f'Public:  {base64.b64encode(key.public_key().public_bytes_raw()).decode()}')"
# Store the PUBLIC key in pmgen/updater/updater.py as SIGNING_PUBLIC_KEY_B64
# Store the PRIVATE key securely (env var, key vault, HSM) — NEVER in the repo
