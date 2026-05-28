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
- Microsoft Access ODBC driver for RIBON lookup support.
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

## Run From Source

Start the desktop app from the repository root so source-mode database lookup can find `catalog_manager.db` in the working directory:

```powershell
.\.venv\Scripts\python.exe -m pmgen.ui.app
```

In a frozen build, the app bootstraps `catalog_manager.db` into the application AppData directory. In source runs, it uses the working-directory copy directly.

## Configuration

PmGen stores normal application settings through `QSettings`, saved Toshiba eService credentials through the OS credential store via `keyring`, and diagnostic logs under `~/.indybiz_pm`.

RIBON lookup uses environment/runtime configuration in [pmgen/io/ribon_db.py](pmgen/io/ribon_db.py). Configure `RIBON_DB_PATH` and `RIBON_DB_PASSWORD` in the local runtime environment rather than committing connection details.

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

For the signed release ZIP and checksum workflow, use:

```powershell
.\.venv\Scripts\python.exe build_sign_zip.py
```

The release script expects a signing certificate at `helpers/IBSCert.pfx`, locates `signtool.exe`, signs generated binaries, creates `PmGen.zip`, and writes `PmGen.zip.sha256`. Publish both artifacts with the GitHub release so the updater can verify downloads.

## Operational Notes

- Keep catalog behavior data-driven through `catalog_manager.db` whenever possible.
- Keep network work, PDF generation, and ODBC calls off the PyQt UI thread.
- Keep `Selection.meta` keys stable because UI and report formatters consume them directly.
- Do not commit local credentials, RIBON connection details, release certificate files, generated logs, or private inventory exports.
- When updating report behavior, add or update fixtures in [tests/example_pm_reports](tests/example_pm_reports).

## License

See [LICENSE](LICENSE).
