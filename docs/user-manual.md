---
title: PmGen User Manual
date: 2026-06-17
version: 3.0.0
audience: PmGen users and service staff
---

# PmGen User Manual

PmGen helps Toshiba service users generate preventive maintenance part recommendations from Toshiba eService PM Support reports. It can process one serial at a time, process many active or inactive machines in bulk, check local inventory, and generate report output for parts ordering.

This manual explains how to use the app, what each screen does, and what the main settings mean.

## Contents

- [Before You Start](#before-you-start)
- [Main Window Overview](#main-window-overview)
- [Sign In And Sign Out](#sign-in-and-sign-out)
- [Single Report Workflow](#single-report-workflow)
- [Understanding Single Report Output](#understanding-single-report-output)
- [Inventory Tab](#inventory-tab)
- [Bulk Runs](#bulk-runs)
- [Bulk Settings Reference](#bulk-settings-reference)
  - [Custom 08 Tracking](#custom-08-sub-code)
  - [Custom 05 Tracking](#custom-05-tracking)
- [Bulk Settings Profiles](#bulk-settings-profiles)
- [Settings Menu Reference](#settings-menu-reference)
- [Catalog Editor](#catalog-editor)
- [Updates](#updates)
- [Closing The App](#closing-the-app)
- [Troubleshooting](#troubleshooting)
- [Glossary](#glossary)

## Before You Start

You need:

- A Windows computer running PmGen.
- A Toshiba eService username and password.
- Network access to Toshiba eService.
- Access to the local RIBON database if your reports need PM unit codes resolved to orderable part numbers.
- The 64-bit Microsoft Access Database Engine driver for RIBON part-number lookup.
- Optional: an inventory CSV export if you want PmGen to compare recommended parts against local stock.

PmGen stores normal preferences locally. If you choose to stay logged in, credentials are stored through the operating system credential store rather than in the app window.

### RIBON Access Driver Setup

PmGen needs the 64-bit Microsoft Access Database Engine driver to read the RIBON Access database. Some RIBON installs download or install the 32-bit/x86 driver. That x86 driver can break PmGen's RIBON lookup because PmGen runs as a 64-bit app.

Before using RIBON part-number lookup:

1. Open Windows `Apps & features` or `Programs and Features`.
2. Uninstall the Microsoft Access Database Engine x86/32-bit driver if it was installed with RIBON.
3. Download the Microsoft Access Database Engine 2016 Redistributable from <https://www.microsoft.com/en-us/download/details.aspx?id=54920>.
4. Choose and install the x64 version from the Microsoft download page.
5. Restart PmGen.

If RIBON lookup or part-number expansion fails with an ODBC driver/provider message, check this driver first. In most cases, removing the x86 driver and installing the x64 driver resolves it.

## Main Window Overview

The main window has a top toolbar, a secondary bar, and tabs.

### Top Toolbar

The top toolbar contains:

| Control | What it does |
|---|---|
| `Settings` | Opens login, output, report, catalog, and display settings. |
| `Bulk` | Starts a new bulk run or opens bulk settings. |
| Update icon | Checks for a newer PmGen release. |
| Minimize | Sends the window to the taskbar. |
| Maximize / Fullscreen | Toggles the window size. |
| Exit | Prompts before closing PmGen. |

The window is frameless. Drag the title area to move it. Drag the window edges to resize it.

### Main Tabs

| Tab | Purpose |
|---|---|
| `Single` | Generate one PM report by serial number. |
| `Inventory` | Import, edit, and cache local inventory. |
| `Bulk HH:MM` | A bulk run tab created when you start a bulk job. Each run gets its own tab. |

The `Single` and `Inventory` tabs cannot be closed. Bulk run tabs can be closed. If a bulk job is still running, PmGen asks before stopping and closing it.

### Secondary Bar On The Single Tab

The Single tab has a bar with:

| Control | What it does |
|---|---|
| Sign-in label | Shows `Not signed in`, `Signing in...`, or the current user. |
| Threshold label | Shows the active due threshold. If optional threshold is off, it shows `100.0%`. |
| Basis label | Shows whether PM life is evaluated by `PAGE` or `DRIVE`. |
| Serial input | Enter a serial number. Input is automatically capitalized. Recent serials are saved in a drop-down list. |
| `Generate` | Generates a single report for the entered serial. |

Keyboard shortcuts:

- `Enter`: generate the single report for the current serial.
- `Ctrl+L`: clear the output window.

## Sign In And Sign Out

### Sign In

1. Open `Settings`.
2. Choose `Login`.
3. Enter your Toshiba eService username and password.
4. Optional: check `Stay Logged In`.
5. Click `Login`.

After login, PmGen downloads device/customer information used by single and bulk reports. If login succeeds, the sign-in label updates and the output window logs success.

### Stay Logged In

When `Stay Logged In` is checked, PmGen attempts to sign in automatically the next time it starts. If auto-login fails, sign in manually from `Settings > Login`.

### Sign Out

1. Open `Settings`.
2. Choose `Logout`.

Logging out clears the remembered-login preference, clears stored credentials, closes any session pools, and updates the main window to show that you are not signed in.

## Single Report Workflow

Use a single report when you want to inspect one machine.

1. Sign in.
2. Open the `Single` tab.
3. Enter a serial number in the serial input box.
4. Confirm the threshold and life basis shown in the secondary bar.
5. Click `Generate` or press `Enter`.
6. Wait for the loading dialog to finish.
7. Review the report text in the output window.

The serial is added to the recent-serial drop-down list. The newest serial stays at the top. PmGen keeps up to 25 recent serials.

If you right-click a row in a bulk run and choose `Inspect / Generate Single Report`, PmGen switches to the Single tab, fills in that serial, and generates a single report.

## Understanding Single Report Output

A single report usually includes:

| Section | Meaning |
|---|---|
| Header | Model, serial, last reported date, and unpacking date when available. |
| Customer | Customer name from Toshiba eService when available. Inactive machines with no assigned customer show `(No Customer Assigned)`. |
| System alerts | Warnings generated by PmGen, such as old unpacking-date alerts. These can be disabled in settings. |
| Due threshold and basis | The threshold and page/drive basis used for the report. |
| Counters | Color, black, DF, and total counters when present in the PM Support report. |
| Highest Wear Items | The highest-wear canon items, their life percentage, and whether they are due. |
| Final Parts - Over 100% | Parts selected because the PM unit life is over 100%. |
| Final Parts - Threshold | Parts selected only because the optional threshold is enabled and the item is above that threshold. |

If `Show All Items` is off, the report focuses on due items. If `Show All Items` is on, the report also includes not-due/watch items so you can see more of the machine's PM state.

### Error History

When generating a single report, PmGen automatically fetches the device's error history from Toshiba eService (non-fatal: empty list on failure). In the rich report view, error records appear in a dedicated table with error code, date, time, and counter columns. Common error codes (E712, EB50, etc.) are displayed for inspection. This feature runs automatically and requires no additional configuration.

## Inventory Tab

The Inventory tab stores local stock data used by report generation and bulk summary checks.

### Inventory Buttons

| Button | What it does |
|---|---|
| `Import` | Imports an inventory CSV file and converts it into PmGen's inventory table. |
| `Add Item` | Adds a blank row to the inventory table. |
| `Delete` | Deletes selected inventory rows after confirmation. |

### Inventory Table Columns

| Column | Meaning |
|---|---|
| `Part Number` | The orderable part number. PmGen normalizes this for matching. |
| `Unit Name` | The PM unit or item name associated with the part. PmGen normalizes this for matching. |
| `Quantity` | Quantity on hand. |
| `Unit Cost` | Cost per unit. |
| `Total Cost` | Quantity multiplied by unit cost. This is calculated automatically. |

You can edit most cells directly in the table. `Total Cost` is calculated and is not meant to be edited directly.

### Import Inventory

1. Open the `Inventory` tab.
2. Click `Import`.
3. Select the inventory CSV file.
4. PmGen processes the file and fills the table.
5. Confirm the status label shows the loaded file name.

PmGen automatically saves the inventory table to a local cache. The cached inventory is restored the next time the app opens.

### Add Or Edit Inventory Manually

1. Click `Add Item`.
2. Edit the new row's part number, unit name, quantity, and cost.
3. PmGen automatically saves the changes.

### Delete Inventory Rows

1. Select one or more rows.
2. Click `Delete`.
3. Confirm deletion.

## Bulk Runs

Bulk runs process many serial numbers in the background.

### Start A Bulk Run

1. Sign in.
2. Open `Bulk > Bulk Settings` and confirm the options.
3. Open `Bulk > New Bulk Run`.
4. PmGen creates a new tab named like `Bulk 14:30`.
5. Watch the progress bar, table, and run log.

Each bulk run creates its own tab. You can start another bulk run after the current workflow is configured, but each run uses the settings captured when it starts.

### Bulk Run Table

Bulk run rows include:

| Column | Meaning |
|---|---|
| `#` | Row number in the current view. |
| `Serial` | Machine serial number. |
| `Model` | Model parsed from the PM Support report. |
| `Customer` | Customer name from Toshiba eService. Unassigned inactive machines show `(No Customer Assigned)`. |
| `Machine State` | `Active` or `Inactive`. |
| `Unpack Date` | Unpacking date parsed from 08 Setting Mode data when available. |
| Custom 08 column | Appears only when Custom 08 Tracking is configured. |
| Custom 05 column | Appears only when Custom 05 Tracking is configured. |
| `Status` | Current row state: `Queued`, `Processing`, `Done`, `Failed`, or `Filtered`. |
| `Result` | Highest wear percentage, filter reason, or error text. |

You can sort the table by clicking column headers. Status and percentage columns use custom sorting so results are easier to scan.

### Bulk Run Controls

| Control | What it does |
|---|---|
| Status label | Shows the current bulk operation. |
| Progress bar | Shows completed serials compared to total serials. |
| Search box | Filters rows by serial, model, customer, or machine state. |
| `Export` | Exports the current table view to `.xlsx` or `.csv`. Sorting and filtering are respected. |
| `Stop` | Requests the bulk job to stop. Current work may finish before the job fully stops. |

### Bulk Row Context Menu

Right-click a row and choose `Inspect / Generate Single Report` to generate a single report for that serial.

### Bulk Reports And Output Folder

If `Generate PDF Reports` is enabled, PmGen writes reports to the configured output directory. It creates a dated folder such as:

```text
SelectedOutputFolder/2026-06-03/
```

If that folder already exists, PmGen creates a numbered folder such as `2026-06-03 (1)`.

Bulk output can include:

- Individual PDF reports for successful, unfiltered serials.
- `Final_Summary.pdf`, which ranks the top machines and combines selected parts.
- Table export files if you use the `Export` button.

Filtered rows do not generate individual PDF reports and are not included in the final summary's top report list.

## Bulk Settings Reference

Open `Bulk > Bulk Settings`.

| Setting | What it does |
|---|---|
| `Top N serials` | Number of highest-wear successful machines to include in the final summary. |
| `Parallel workers` | Number of concurrent worker sessions used during bulk processing. Higher values can be faster but heavier on eService and your machine. Valid range is 1 to 16. |
| `Active/Inactive filter` | Controls which machines are included: `Both`, `Active`, or `Inactive`. |
| `Generate PDF Reports` | When checked, PmGen creates individual PDFs and a final summary PDF. When unchecked, the bulk table is populated but PDFs are not generated. |
| `Out Dir` | Folder where PDF output folders are created. Required when PDF generation is enabled. |
| `Browse` | Opens a folder picker for `Out Dir`. |
| `Blacklist` | Serial numbers or wildcard patterns to skip. Separate entries with commas or new lines. Patterns are matched against uppercase serials. |
| `Exclude if NEWER than (Months)` | Filters out machines whose unpacking date is newer than the selected number of months. Useful when you only want older installations. |
| `Exclude if OLDER than (Months)` | Filters out machines whose unpacking date is older than the selected number of months. Useful when excluding very old installations. |
| `Custom 08 Tracking - Column Name` | Adds a custom column to the bulk table for a value parsed from 08 Setting Mode data. Leave blank if not needed. |
| `Custom 08 Tracking - 08 Code` | The numeric 08 Setting Mode code to read. `0` disables custom 08 tracking. |
| `Custom 08 Tracking - 08 Sub Code` | The numeric 08 Setting Mode sub code to read. `0` for default/0. |
| `Custom 05 Tracking - Column Name` | Adds a custom column to the bulk table for a value parsed from 05 Adjustment Mode data. Leave blank if not needed. |
| `Custom 05 Tracking - 05 Code` | The numeric 05 Adjustment Mode code to read. `0` disables custom 05 tracking. |
| `Custom 05 Tracking - 05 Sub Code` | The numeric 05 Adjustment Mode sub code to read. `0` default/0. |

Click `Save` to store bulk settings.

### Date Filter Examples

- To skip very new machines, enable `Exclude if NEWER than (Months)` and enter `6`.
- To skip very old machines, enable `Exclude if OLDER than (Months)` and enter `48`.
- If no unpacking date is available for a machine, PmGen keeps the row because it cannot evaluate the date filter.

## Bulk Settings Profiles

Profiles let you save, load, and delete named snapshots of all bulk settings. This is useful when you regularly switch between different bulk configurations (e.g., one profile for active machines with PDFs, another for inactive machines without PDFs).

### Profile Controls

Open `Bulk > Bulk Settings`. The profile controls are at the top of the dialog:

| Control | What it does |
|---|---|
| Profile drop-down | Selects a saved profile. Changing the selection loads that profile's settings immediately. |
| `Save As New` | Saves the current settings as a new named profile. Enter a unique name in the prompt. |
| `Save` | Overwrites the currently selected profile with the current settings. |
| `Delete` | Deletes the currently selected profile after confirmation. The "Default" profile cannot be deleted. |

A "Default" profile is created automatically the first time you use profiles. The last-used profile is remembered and restored when you reopen Bulk Settings.

## Settings Menu Reference

Open `Settings` from the top toolbar.

| Menu item | What it does |
|---|---|
| `Login` | Opens the Toshiba eService login dialog. |
| `Logout` | Signs out, clears remembered login preference, and closes stored sessions. |
| `Optional Threshold` | Configures whether items below 100% life can still be treated as due. |
| `Life Basis` | Chooses whether PM life is evaluated primarily by page counters or drive counters. |
| `Show All Items` | Toggles whether reports include not-due/watch items in addition to due items. |
| `Rich Report View` | Toggles between the widget-based rich report view (with donut chart, error history, and card layout) and the plain text output. |
| `Colorized Output` | Toggles color highlighting in the Single tab output (text mode only). |
| `Appearance` | Opens display preferences: light/dark theme toggle and window corner rounding slider. |
| `Clear Output Window` | Clears the Single tab output. Same as `Ctrl+L`. |
| `About` | Shows the PmGen version and supported model count/list. |
| `Catalog Editor` | Opens the catalog editor for models, PM units, canon mappings, per-color units, and quantity overrides. |
| `Enable System Alerts` | Toggles alert output in reports. |

### Optional Threshold

Items over 100% life are always due. Optional Threshold lets you mark items as due earlier than 100%.

For example, if Optional Threshold is enabled and set to `80%`, an item at `85%` can appear in the threshold section. If Optional Threshold is disabled, only items at or over `100%` are treated as due.

The threshold label in the Single tab shows the active value. When optional threshold is disabled, the app shows `Threshold: 100.0%`.

### Life Basis

Life Basis controls which counter type PmGen uses first:

| Option | Meaning |
|---|---|
| `Page` | Use page-counter life first. |
| `Drive` | Use drive-counter life first. |

If the selected basis is missing for a report item, PmGen falls back to the other available basis.

### Show All Items

When off, reports focus on due items. When on, reports also show non-due/watch items sorted by wear. This is useful for inspection and troubleshooting.

### Rich Report View

When on (default), PmGen displays reports as a rich widget view with:

- A donut chart showing due vs. OK items with the highest wear percentage.
- Color-coded sections for model info, alerts, counters, error history, wear items, and final parts.
- Error history table showing recent Toshiba device error codes with dates and counters.
- Visual wear breakdown with life percentages.

When off, PmGen uses the plain text output view (legacy mode). The setting persists across sessions.

### Colorized Output

When on, PmGen applies syntax highlighting/coloring to the Single tab report text (text mode only). Turn it off if you prefer plain output. Has no effect when Rich Report View is enabled.

### Appearance

Open `Settings > Appearance` to configure:

| Setting | What it does |
|---|---|
| Theme | Toggles between Dark (default) and Light mode. |
| Corner Roundness | Adjusts window corner rounding from sharp (0) to fully rounded (100). Default is 50. Changes apply immediately. |

### Enable System Alerts

When on, PmGen displays system alert text in generated reports. Alerts can include warnings such as old unpacking dates.

## Catalog Editor

Open `Settings > Catalog Editor`.

The Catalog Editor controls the data PmGen uses to turn raw PM Support report rows into PM units and orderable part selections. Use it carefully. Incorrect catalog edits can change report results.

### Catalog Editor Common Controls

| Control | What it does |
|---|---|
| `Save All` | Saves every dirty tab in the safe dependency order. Enabled only when at least one tab has unsaved changes. |
| `Save` | Saves the current tab. |
| `Discard` | Reloads the current tab from the database and drops unsaved edits for that tab. |
| `Add` | Adds a row or entry, when available for the tab. |
| `Delete` | Deletes the selected row or entry, when available for the tab. |
| `*` in a tab title | Marks that tab as having unsaved changes. Example: `PM Units *`. |

When any tab has unsaved changes, PmGen shows:

```text
Save changes to make updated catalog data available across all Catalog Editor tabs.
```

This matters because some tabs depend on data from other tabs. For example, PM Units use canon items, and Models use PM Units.

If you close the Catalog Editor with unsaved changes, PmGen asks whether to close anyway.

### Suggested Catalog Editing Order

For new catalog data, use this order:

1. `Canon Mappings` if you need a new canon item name from raw report text.
2. `PM Units` to define the PM unit and select canon items inside it.
3. `Models` to link PM units to machine models.
4. `Per Color Units` if a color-specific PM unit should not be counted more than once for the same color.
5. `Quantity Overrides` if a PM unit needs a fixed quantity.

The visible tab order is optimized for browsing. `Save All` uses a safe save order internally so dependent tabs can refresh correctly.

### Models Tab

The Models tab links machine models to PM units.

| Area | What it does |
|---|---|
| Model table | Shows supported models. Select a model to edit its linked PM units. |
| `Units linked to selected model` | Check or uncheck the PM units that apply to the selected model. |

Buttons:

- `Add`: adds a new model row.
- `Delete`: marks the selected model for deletion.
- `Save`: saves model names and linked PM units.
- `Discard`: reloads the tab from the database.

Model names are normalized to uppercase. Duplicate or blank model names are not allowed.

### PM Units Tab

The PM Units tab defines PM units and which canon items each unit contains.

| Area | What it does |
|---|---|
| PM Unit table | Shows PM unit names. Select a PM unit to edit its canon items. |
| `Canon items in selected unit` | Check canon items that belong to the selected PM unit. |

Canon items are gathered from the Canon Mappings table. If a selected canon item no longer exists in Canon Mappings, it is shown with `(not in Canon Mappings)` and must be fixed before saving.

Buttons:

- `Add`: adds a new PM unit.
- `Delete`: marks the selected PM unit for deletion.
- `Save`: saves PM units and their canon item selections.
- `Discard`: reloads the tab from the database.

### Canon Mappings Tab

The Canon Mappings tab controls how raw PM Support item text becomes a standardized canon item name.

Table columns:

| Column | Meaning |
|---|---|
| `ID` | Database ID. This is read-only. |
| `Pattern` | Regex pattern used to match raw report item text. |
| `Template` | Canon item template produced when the pattern matches. |

Buttons and tools:

| Control | What it does |
|---|---|
| `Add` | Adds a new mapping row. |
| `Delete` | Deletes the selected mapping row. |
| `Save` | Validates and saves mappings. |
| `Discard` | Reloads mappings from the database. |
| `Show Tokens` / `Hide Tokens` | Shows or hides built-in regex helper tokens. |
| Regex tester input | Lets you type sample raw item text. |
| `Test` | Tests the sample against all mappings. First match wins at runtime. |

Built-in regex helper tokens include:

| Token | Meaning |
|---|---|
| `{SPC}` | Optional whitespace. |
| `{SPC1}` | One or more whitespace characters. |
| `{LP}` | Optional left parenthesis. |
| `{RP}` | Optional right parenthesis. |
| `{COLOR}` | Color/channel variants such as K/C/M/Y. |
| `{DF_TYPE}` | Document feeder variants. |
| `{SFB_BYPASS}` | SFB/BYPASS alternative. |

Validation prevents blank rows, duplicate patterns, unknown helper tokens, invalid regex, and template tokens that do not exist in the regex named groups.

### Per Color Units Tab

The Per Color Units tab prevents double-counting color-specific PM units.

Some PM units are sold or handled by color: `K` for black, `C` for cyan, `M` for magenta, and `Y` for yellow. A PM Support report can show several due canon items inside the same color unit. If those items all point to the same PM unit, PmGen should usually recommend one unit for that color, not one unit for every due item.

Example: if `DRUM[K]` and `GRID[K]` are both due and both belong to the same black PM unit, checking that PM unit here tells PmGen to count `1` black unit, not `2`. If black and cyan are both due, PmGen can count `2` total: one for black and one for cyan.

Use this tab for PM units that are color-specific kits and may contain multiple canon items for the same color. Do not use it for normal one-per-machine kits.

Use the checkbox list to select PM units. The list comes from the PM Units tab. Stale items are shown with `(not in PM Units)` and must be fixed before saving.

Buttons:

- `Save`: saves the selected per-color PM units.
- `Discard`: reloads the tab from the database.

### Quantity Overrides Tab

The Quantity Overrides tab sets fixed quantities for PM units.

Table columns:

| Column | Meaning |
|---|---|
| `Override` | Check this to enable an override for the PM unit. |
| `PM Unit` | PM unit name. This is selected from existing PM Units. |
| `Quantity` | Fixed quantity to use when the override is enabled. |

Use this when grouping logic would produce the wrong quantity for a vendor kit and the PM unit needs a known fixed count.

Buttons:

- `Save`: saves checked overrides and quantities.
- `Discard`: reloads the tab from the database.

Checked rows must have a numeric quantity. Stale PM units are shown with `(not in PM Units)` and must be fixed before saving.

## Updates

The update button checks GitHub Releases for a newer PmGen version.

- PmGen also checks silently shortly after startup.
- If an update is found, PmGen asks whether to install it.
- During update, a progress dialog shows download and extraction progress.
- Updates are intended for compiled/frozen builds. Source-mode runs show a message instead of updating.

## Closing The App

When you exit PmGen, the app saves recent serial history.

If the Inventory tab contains items, PmGen asks whether to keep or delete the inventory cache:

| Choice | What happens |
|---|---|
| `Keep` | Keeps cached inventory for the next session. |
| `Delete` | Deletes the inventory cache before closing. |
| `Cancel` | Cancels closing and returns to the app. |

If a bulk job is running and you close its tab, PmGen asks before stopping and closing it.

## Troubleshooting

### Generate says you must be logged in

Sign in from `Settings > Login`. If you expected auto-login, the saved session may have expired or credentials may need to be re-entered.

### Login fails

Check your Toshiba eService username/password and network access. Sign out and sign in again if credentials changed.

### A serial generates an error

Confirm the serial exists in Toshiba eService and that the PM Support report is available for that machine. Try a single report first if the error happened during bulk processing.

### Bulk run says output directory is not set

Open `Bulk > Bulk Settings`, enable or confirm `Generate PDF Reports`, and choose an `Out Dir`. If you do not want PDFs, uncheck `Generate PDF Reports`.

### Bulk rows show `Filtered`

The row matched a bulk filter, usually `Exclude if NEWER than` or `Exclude if OLDER than`. Filtered rows remain visible in the table but do not produce PDFs.

### Customer is blank or says `(No Customer Assigned)`

PmGen reads customer names from Toshiba eService. Some inactive machines have no assigned customer. Those rows display `(No Customer Assigned)`.

### Inventory is missing from reports or summary checks

Open the Inventory tab and confirm inventory is loaded. Import a CSV again if needed. PmGen uses the cached inventory table for inventory comparisons.

### RIBON lookup or part-number expansion fails

Make sure the local RIBON database is available and that the 64-bit Microsoft Access Database Engine driver is installed. If RIBON installed the x86/32-bit driver, uninstall it first, then install the x64 driver from <https://www.microsoft.com/en-us/download/details.aspx?id=54920>. Restart PmGen after changing drivers.

### Catalog Editor will not save

Read the validation message. Common causes include blank names, duplicate model/unit names, stale canon items, stale PM units, invalid regex, or non-numeric quantity override values.

### Catalog changes do not appear in another tab

Save the changed tab or click `Save All`. Dependent tabs refresh from saved catalog data.

## Glossary

| Term | Meaning |
|---|---|
| PM Support report | Toshiba eService report containing PM counters and unit rows. |
| 08 Setting Mode | Toshiba data used by PmGen for unpacking date and optional custom bulk tracking. |
| Canon item | A standardized internal name for a raw PM item from a report. |
| PM Unit | A catalog unit or kit that can be selected for a model and resolved to parts. |
| RIBON | Local database used to resolve PM units to orderable part numbers. |
| Threshold | Optional percentage below 100% where PmGen can mark an item due early. |
| Life basis | Whether page counters or drive counters are preferred when calculating life used. |
| Per-color unit | A color-specific PM unit that PmGen counts once per due color, even if several items inside that same color unit are due. |
| Quantity override | A fixed quantity rule for a PM unit. |
| Bulk final summary | PDF combining the top machines from a bulk run and their selected parts. |
| Bulk profile | A named snapshot of all bulk settings that can be saved, loaded, and deleted. |
| Rich report view | The widget-based report display with donut chart, error history, and card layout. |
| Donut chart | A ring chart in the rich report view showing due vs. OK item counts with center text. |
| Error history | Toshiba device error codes, dates, and counters fetched automatically during single report generation. |
| 05 Adjustment Mode | Toshiba service data mode containing technician-applied adjustment values (voltage, registration, fuser offsets, etc.). Identified by numeric codes and optional sub-codes. |
| Custom 08 Tracking | An optional bulk column for values parsed from 08 Setting Mode data (e.g., firmware version, serial counter). |
| Custom 05 Tracking | An optional bulk column for values parsed from 05 Adjustment Mode data (e.g., voltage, registration offset). Configured with a column name, numeric 05 code, and optional sub-code. |
| Corner roundness | Adjustable window corner rounding (0–100) configured in the Appearance dialog. |
