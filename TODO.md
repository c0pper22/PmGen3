# PmGen TODO

> Last updated: 2026-06-10

---

## ✅ Recently Completed

- [x] Converted blacklist setting from text box to editable table (+ Add / − Remove)
- [x] Added 08 subcode support (custom_08_sub field in BulkConfig and UI)
- [x] Added Custom 05 Adjustment tracking (custom_05_name/code/sub)
- [x] Generic CSV parser handles both 08 and 05 with subcode filtering
- [x] Delayed auto-login until after UI renders (1500ms → fixes false failures)
- [x] Redesigned Bulk Settings dialog — horizontal 3-column layout (980×700)
- [x] Empty sub fields now match sub=0 (e.g., `9903, , DF-31,`)

---

## 🔧 Core Features

- [ ] **DSDF & RSDF detection** — correct part selection based on document feeder type
- [X] **Single report UI rework** — replace plain-text output with widgets/panels (collapsible sections, kit tables, color-coded due flags, graphs)
- [X] **Recent Error Codes section** — fetch and display recent device error/fault codes in a dedicated tab or panel alongside PM data
- [ ] **automatic Ribon update detection** - reverse ribon.exe, figure out how to automatically check if ribon is up to date or not. (if possible update it, this is a long shot.)
---

## 📊 Custom CSV Tracking

- [ ] **E2E offline tests for 08/05/Error History CSVs** — test `_parse_code_from_csv_bytes` with real example files (already have `08_example.csv` and `05_example.csv`)
- [X] **Subcode UI hint** — add "0 = subcode 0 or empty" label/placeholder near the sub spinbox so users know empty subs match

---

## 📋 Bulk Operations

- [ ] **Paste multi-line into blacklist table** — intercept Ctrl+V to split newlines into separate rows
- [ ] **Duplicate detection in blacklist** — warn when adding an already-listed serial (case-insensitive)
- [ ] **Export bulk results to CSV** — export the bulk results table (with all columns) to a `.csv` file
- [ ] **Resume interrupted bulk runs** — persist state so a cancelled/killed bulk can be restarted
- [ ] **Estimated time remaining** — show ETA based on completed serials vs total
- [ ] **Column reordering in bulk tables** — allow drag-and-drop column reordering, persist layout

---

## 🖥️ UI / UX

- [ ] **Fix Single (TEXT GEN) Light Mode** - fix colors during light mode for text based single gen. 
- [ ] **Multi-select machine filter** — checkboxes for Active/Inactive instead of single dropdown
- [ ] **"Test Connection" button** in login dialog — verify credentials before saving
- [ ] **Keyboard shortcuts** — Ctrl+B for bulk, Ctrl+R for single report, F5 for refresh, Esc to close dialogs
- [ ] **Right-click "Copy Value"** on bulk table cells
- [ ] **Progress bar color changes** — green for Done, red for Failed, yellow for Processing
- [ ] **Toolbar button tooltips** — add descriptive tooltips to all toolbar icons

---

## 🔌 External Integrations

- [ ] **Check for RIBON updates** — poll RIBON accdb for schema or data changes
- [ ] **Export to Excel (.xlsx)** — richer export format with styled headers and conditional formatting
- [ ] **Email report summaries** — optionally email the final summary PDF to configured addresses

---

## 🧪 Testing & Quality

- [ ] **Unit tests for `_parse_code_from_csv_bytes`** — cover 08, 05, sub=0, sub>0, empty sub, trailing commas, large files
- [ ] **Integration test for full 05 flow** — configure → fetch → parse → display in table
- [ ] **CI pipeline** — GitHub Actions for linting (ruff) + tests on push/PR
- [ ] **Coverage target >80%** — add coverage badge and enforce in CI

---

## 🛡️ Robustness

- [ ] **Serial number validation** — validate serial format before starting bulk run
- [ ] **Network retry logic** — retry failed `get_service_file_bytes` calls with exponential backoff
- [ ] **Session pool health check** — detect dead sessions in pool and refresh them
- [ ] **Graceful shutdown** — ensure threads and sessions are cleaned up on window close
- [ ] **Crash dump on fatal error** — write a minidump or stack trace to disk for debugging

---

## 🎨 Polish

- [ ] **Undo/redo for blacklist table** — Ctrl+Z/Y support for add/remove operations
- [ ] **Dark/light theme persistence** — remember and restore theme on restart without flash
- [ ] **Animated transitions** — smooth panel expand/collapse (where Qt permits)
- [ ] **App icon for notifications** — custom taskbar/system-tray icon