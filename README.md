# PmGen

PmGen is a Windows desktop application for generating preventive maintenance part recommendations from Toshiba e-STUDIO service reports. It signs into Toshiba eService, downloads PM Support and 08 Setting Mode data, parses wear counters, applies a catalog-driven rules pipeline, checks local inventory, resolves PM unit codes to orderable part numbers, and produces text, PDF, Excel, and bulk summary outputs.

## Features

- Single-serial PM report generation from Toshiba eService data.
- Bulk processing for active serials with background worker threads.
- Catalog-driven model, PM unit, canon mapping, per-color unit, and quantity override logic.
- Inventory CSV import, editing, caching, and stock coverage checks.
- RIBON Access database lookup for PM unit code to part-number resolution.
- Individual report PDFs and consolidated bulk `Final_Summary.pdf` generation.
- GitHub-release updater with ZIP checksum validation, safe extraction, install locking, and rollback.
- Rolling diagnostic logs for app and updater troubleshooting.

## Documentation

User-facing usage documentation is available in [docs/user-manual.md](docs/user-manual.md).

Full project documentation is available in [docs/project-summary.md](docs/project-summary.md) and [docs/project-summary.docx](docs/project-summary.docx).

Architecture diagrams are stored as editable draw.io files and exported PNGs under [docs/diagrams](docs/diagrams):

- [docs/diagrams/high-level-architecture.drawio.png](docs/diagrams/high-level-architecture.drawio.png)
- [docs/diagrams/processing-pipeline.drawio.png](docs/diagrams/processing-pipeline.drawio.png)
- [docs/diagrams/component-relationships.drawio.png](docs/diagrams/component-relationships.drawio.png)
- [docs/diagrams/data-model.drawio.png](docs/diagrams/data-model.drawio.png)
- [docs/diagrams/deployment-infrastructure.drawio.png](docs/diagrams/deployment-infrastructure.drawio.png)

## Requirements

- Windows.
- Python 3.11 or newer recommended.
- Toshiba eService account access for live report downloads.
- Microsoft Access Database Engine x64 driver for RIBON lookup support.
- Local RIBON database access when part-number expansion is required.
- Windows SDK `signtool.exe` and a code-signing certificate for release builds.

Runtime dependencies are pinned in [requirements.txt](requirements.txt).

## Setup

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For development and tests, install the test tools used by the suite if they are not already present in the environment:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pytest-qt openpyxl packaging
```

### RIBON Microsoft Access Driver

PmGen uses a 64-bit Python/runtime process, so RIBON lookup requires the 64-bit Microsoft Access Database Engine driver. Some RIBON installations download or install the 32-bit/x86 Access Database Engine driver, which can cause ODBC connection failures even when RIBON itself appears installed.

Recommended setup:

1. In Windows `Apps & features` or `Programs and Features`, uninstall the existing Microsoft Access Database Engine x86/32-bit driver if it is installed by RIBON.
2. Install the 64-bit Microsoft Access Database Engine 2016 Redistributable from Microsoft: <https://www.microsoft.com/en-us/download/details.aspx?id=54920>.
3. Choose the x64 installer from the Microsoft download page.
4. Restart PmGen after installing the driver.

If part-number expansion or RIBON lookup fails with an ODBC driver/provider error, verify that the x86 driver was removed and the x64 driver is installed.

## Run From Source

Start the desktop app from the repository root so source-mode database lookup can find `catalog_manager.db` in the working directory:

```powershell
.\.venv\Scripts\python.exe -m pmgen.ui.app
```

In a frozen build, the app bootstraps `catalog_manager.db` into the application AppData directory. In source runs, it uses the working-directory copy directly.

## Configuration

PmGen stores normal application settings through `QSettings`, saved Toshiba eService credentials through the OS credential store via `keyring`, and diagnostic logs under `~/.indybiz_pm`.

RIBON lookup uses environment/runtime configuration in [pmgen/io/ribon_db.py](pmgen/io/ribon_db.py). Configure `RIBON_DB_PATH` and `RIBON_DB_PASSWORD` in the local runtime environment rather than committing connection details. RIBON lookup also requires the 64-bit Microsoft Access Database Engine driver described in [RIBON Microsoft Access Driver](#ribon-microsoft-access-driver).

The inventory cache is stored as `inventory_cache.csv` in the application AppData directory. It is populated from the Inventory tab by importing an inventory CSV.

## How It Works

The main processing flow is:

1. The UI starts a `SingleReportWorker` or `BulkRunner`.
2. `SessionPool` logs into Toshiba eService and provides authenticated sessions.
3. PM Support bytes are downloaded and parsed by `ParsePmReport()`.
4. Raw unit descriptors are normalized with catalog regex mappings.
5. `run_rules()` applies the rule pipeline: life calculation, kit linking, unit grouping, quantity overrides, inventory checks, and RIBON expansion.
6. Report formatters generate UI text, individual PDFs, and bulk summaries.

The rule pipeline is defined in [pmgen/engine/run_rules.py](pmgen/engine/run_rules.py). Individual rule implementations live in [pmgen/rules](pmgen/rules).

## Project Structure

```text
PmGen/
|-- build_sign_zip.py          # PyInstaller build, signing, ZIP, and checksum pipeline
|-- create_database.py         # Catalog seed data and canon mapping source
|-- catalog_manager.db         # Bundled SQLite catalog
|-- pmgen.spec                 # PyInstaller spec for app and updater
|-- requirements.txt           # Pinned dependencies
|-- pmgen/
|   |-- canon/                 # Canonical unit normalization
|   |-- catalog/               # Catalog helper models
|   |-- engine/                # Rule orchestration and report formatting
|   |-- io/                    # HTTP, SQLite, RIBON, and serial parsing integrations
|   |-- parsing/               # PM Support report parser
|   |-- rules/                 # Maintenance-selection rules
|   |-- system/                # Logging, crash handlers, PyQt slot wrapper
|   |-- ui/                    # PyQt6 application and UI workers
|   |-- updater/               # GitHub updater and external install process
|   |-- types.py               # Shared dataclass contracts
|-- tests/                     # Regression, UI model, and updater tests
|-- docs/                      # Project documentation and diagrams
```

The `_internal/` directory mirrors packaged runtime content and should generally be treated as generated distribution support.

## Tests

Run the full test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The tests cover full PM report fixture processing, stable rule metadata contracts, PDF summary generation, bulk worker date filtering, UI table model behavior, catalog editor behavior, main-window behavior, and updater hardening/rollback paths.

## Build And Release

Build the PyInstaller distribution directly with:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean pmgen.spec
```

The spec file produces two executables:
- `dist/PmGen/PmGen.exe` — the main application.
- `dist/PmGen/updater.exe` — the external update installer.

For the signed release ZIP and manifest signing workflow, use:

```powershell
.\\.venv\\Scripts\\python.exe build_sign_zip.py
```

The release script:
1. Runs PyInstaller from the spec.
2. Signs all EXEs, DLLs, and PYDs with the PFX code-signing certificate using `signtool.exe`.
3. Zips the `dist/PmGen` directory into `final/PmGen.zip`.
4. Reads the app version from `pmgen/updater/updater.py`.
5. Creates `final/manifest.json` with the ZIP's SHA-256 hash, size, version, and metadata.
6. Signs the manifest with the Ed25519 private key, writing `final/manifest.json.sig`.

Requires:
- `PMGEN_SIGNING_KEY` environment variable set to the base64-encoded Ed25519 32-byte private key.
- A code-signing PFX at `helpers/IBSCert.pfx`.
- Windows SDK `signtool.exe` on the `PATH` or auto-discovered.

Publish all three artifacts (`PmGen.zip`, `manifest.json`, `manifest.json.sig`) with the GitHub release so the updater can verify downloads.

### Generating signing keys

To generate a new Ed25519 keypair for release signing:

```powershell
.\\.venv\\Scripts\\python.exe generate_signing_keys.py -o keys/
```

Or, using the one-liner:

```
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; key = Ed25519PrivateKey.generate(); print(f'Private: {base64.b64encode(key.private_bytes_raw()).decode()}'); print(f'Public:  {base64.b64encode(key.public_key().public_bytes_raw()).decode()}')"
```

- Store the **public** key in `pmgen/updater/updater.py` as `SIGNING_PUBLIC_KEY_B64`.
- Store the **private** key securely (environment variable, key vault, HSM). Never commit it to the repository.

## Updater

PmGen includes a secure, cryptographically verified auto-updater that fetches releases from GitHub.

### Update flow

1. **Check**: The app fetches the latest GitHub release from `https://api.github.com/repos/c0pper22/PmGen/releases/latest`. It looks for three required assets: `manifest.json`, `manifest.json.sig`, and `PmGen.zip`.
2. **Verify manifest signature**: The updater downloads `manifest.json` and `manifest.json.sig`, then verifies the Ed25519 signature using the hardcoded public key (`SIGNING_PUBLIC_KEY_B64`). If signature verification fails, the update is rejected.
3. **Parse manifest**: The verified manifest is parsed and validated (schema version, app ID, signature algorithm, version, asset name, SHA-256 format, size, minimum supported version).
4. **Version comparison**: If the manifest version is newer than `CURRENT_VERSION`, an update is available. Rollback is prevented by checking `update_state.json`.
5. **Download**: The ZIP is downloaded with a progress bar. Content-Length is checked against the manifest, and the SHA-256 hash is computed and compared to the manifest after download.
6. **Extract**: The verified ZIP is extracted to a temp directory with path-traversal protection. Extraction metadata is written to `.pmgen_verified_update.json`.
7. **Restart**: The app saves the installed version to `update_state.json`, stages `updater.exe` to a temp directory, launches it with arguments (extracted payload directory, install target, exe name, parent PID, session ID), and exits.
8. **Install**: The external `updater.exe` (`run_update.py`) waits for the parent process to exit, acquires a lock file, copies files from the extracted payload to the install directory, preserves `catalog_manager.db` and lock files, prunes stale runtime files, and relaunches the app. On failure, it rolls back and relaunches the previous version.

### Signing architecture

PmGen uses two separate signing systems:

| System | Purpose | Key type | Location |
|---|---|---|---|
| Ed25519 manifest signing | Authenticate update manifests | Ed25519 key pair (32-byte) | Public key embedded in `updater.py`; private key in `PMGEN_SIGNING_KEY` env var |
| PFX code signing | Sign Windows binaries (EXE/DLL/PYD) | PFX certificate with timestamping | `helpers/IBSCert.pfx`, applied by `build_sign_zip.py` via `signtool.exe` |

These systems are independent. The Ed25519 key pair is used only for manifest signing and verification during updates. The PFX certificate is used only at build time for Authenticode code signing of distributed binaries.

### Files produced by the build pipeline

All release artifacts are placed in the `final/` directory:

| File | Description |
|---|---|
| `final/PmGen.zip` | Signed, frozen application packaged with PyInstaller |
| `final/manifest.json` | JSON metadata with version, SHA-256, size, release date, and minimum supported version |
| `final/manifest.json.sig` | Base64-encoded Ed25519 signature of `manifest.json` |

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `PMGEN_SIGNING_KEY` | Yes (for builds) | Base64-encoded Ed25519 private key (32 bytes raw). Used by `build_sign_zip.py` to sign `manifest.json`. Never commit this value. |

### State files

| File | Location | Purpose |
|---|---|---|
| `update_state.json` | `~/.indybiz_pm/` | Tracks last installed version and update timestamp for rollback protection |
| `updater.log` | `~/.indybiz_pm/` | Rotating log for the external updater process |
| `.pmgen_update.lock` | Install directory | Prevents concurrent update installations |
| `.pmgen_verified_update.json` | Extracted payload directory | Verification metadata written after secure extraction |

## Operational Notes

- Keep catalog behavior data-driven through `catalog_manager.db` whenever possible.
- Keep network work, PDF generation, and ODBC calls off the PyQt UI thread.
- Keep `Selection.meta` keys stable because UI and report formatters consume them directly.
- Do not commit local credentials, RIBON connection details, release certificate files, generated logs, or private inventory exports.
- When updating report behavior, add or update fixtures in [tests/example_pm_reports](tests/example_pm_reports).

## License

See [LICENSE](LICENSE).
