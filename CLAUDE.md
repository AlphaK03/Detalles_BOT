# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Detalles_BOT** automates extraction of DUA (Declaración Única de Aduanas) data from Costa Rica's TICA customs portal (`https://portaltica.hacienda.go.cr/`). It uses Selenium to navigate the portal, resolve CAPTCHAs via a lookup table, and extract 25+ fields per DUA into a CSV.

## Running the Project

```bash
# Install dependencies
pip install selenium pandas beautifulsoup4 requests selenium-wire

# Run the application (launches Tkinter GUI)
python src/main.py
```

**External requirements** (not pip-installable):
- Edge WebDriver at the path set in `config/machine.json` → `edge_driver_path` (default: `C:/WebDriver/msedgedriver.exe`)
- Input Excel file with DUA rows (column `NroDUA` in format `Aduana-Año-Número`)
- `Names_TicaPortal.xlsx` — CAPTCHA image-URL-to-text lookup table (path: `machine.json` → `names_file_path`)

## Architecture

### Entry point
`src/main.py` adds `src/` to `sys.path` and calls `App().mainloop()`.

### GUI (`src/ui/app.py`)
`App(tk.Tk)` — manages the full UI lifecycle:
- Two tabs: **Procesamiento** (file/sheet selection, live counters, log console) and **Configuración** (threads, timeout, retries, paths, headless toggle)
- Processing is launched in a daemon thread that spawns a `ThreadPoolExecutor`. All UI updates from worker threads go through `self.after(0, fn)`.
- `_GuiLogHandler` pipes log records into a color-coded `ScrolledText` widget.
- Driver update dialog: reads Edge version from Windows registry, compares with driver, downloads matching driver via `driver_updater.py`.

### Pluggable flow system (Strategy Pattern)
The key abstraction for multi-bot reuse:

| File | Role |
|------|------|
| `src/flows/base_flow.py` | `BaseFlow` ABC — defines the contract every bot implements |
| `src/flows/detalles_flow.py` | `DetallesFlow(BaseFlow)` — navigation and data extraction for this bot |
| `src/core/processor.py` | `DUAProcessor` — generic engine: CAPTCHA, retries, CSV write, duplicate detection |
| `src/core/browser.py` | `create_edge_driver()` — Edge WebDriver factory with request interceptor |

**`BaseFlow` contract** — four methods to implement:
- `start_url` (property): Portal entry URL
- `on_before_form(driver, attempt, timeout)`: Optional hook called before form fill (e.g., dismissing portal error pages on retry)
- `fill_form(driver, row, captcha_text, timeout)`: Fill and submit the search form
- `wait_for_result(driver, timeout)`: Wait until the result page is ready
- `extract_data(page_source) -> pd.DataFrame`: Parse HTML and return a single-row DataFrame

**`DetallesFlow` details**: Sets browser zoom to 25% in `fill_form` (portal elements are small). The `on_before_form` hook is activated from attempt 3+ to auto-dismiss a rectification page the portal sometimes shows.

**To create a new bot:** subclass `BaseFlow`, implement the 4 methods, pass the instance to `DUAProcessor`. The generic engine handles everything else.

### Processing engine (`src/core/processor.py`)
`DUAProcessor` — one instance per worker thread, each with its own Selenium driver.

**Retry loop** per DUA:
1. Navigate to `flow.start_url`
2. Call `flow.on_before_form()` (optional hook)
3. Resolve CAPTCHA: extract image URL from page → look up text in `names_df` (no OCR)
4. Call `flow.fill_form()`, then `flow.wait_for_result()`
5. Call `flow.extract_data()`, validate non-empty and has `numero_del_dua`
6. Check global `_PROCESSED_DUAS` set (thread-safe lock) — skip if already written
7. Acquire `self.lock` → write CSV row → append to processed log
8. On exception: retry; on max retries: log to failed file and restart driver

**DNS resilience**: `_wait_for_portal()` polls the portal until HTTP 200, handling `ERR_NAME_NOT_RESOLVED` gracefully.

### WebDriver factory (`src/core/browser.py`)
`create_edge_driver()`:
- Creates isolated Edge session in `temp/edge/` (not system temp)
- **Request interceptor** aborts `.png`, `.jpg`, `.css`, `.woff`, and font requests — significantly speeds up page loading
- Increases urllib3 connection pool size from 1 to 10 to reduce TCP churn
- Daemon thread cleans up orphaned session dirs from crashed runs every 30 min
- Wraps `driver.quit()` to also remove the session dir

### Configuration (two files, clearly separated)

| File | Contains | Changes when |
|------|----------|--------------|
| `config/machine.json` | `base_path`, `output_base_path`, `names_file_path`, `edge_driver_path`, `max_retries`, `timeout`, `cant_hilos`, `headless` | Changing machine or adjusting processing parameters |
| `config/session.json` | `sheet_name`, `input_file_path`, `progress.{sheet_key}`, `totals.{sheet_key}` | UI saves automatically on each run |

`normalize_key(name)` in `src/utils.py` converts sheet names to JSON-safe keys (lowercase, stripped of special chars) — used as the dict key in `progress` and `totals`.

Output paths are always **computed at runtime** by `compute_output_paths()` in `src/utils.py` — never stored in config.

### Resume mechanism (two levels)
1. **Row index** (`session.json` → `progress.{sheet_key}`): The GUI skips rows up to the last saved index. Updated via `_last_saved_index` guard in `app.py` to prevent race conditions.
2. **DUA IDs** (`processed_log` text file): `load_processed_duas_from_log()` pre-populates `_PROCESSED_DUAS` before starting the executor — prevents duplicate CSV writes if the row index and actual writes drifted.

Both levels must agree for a safe resume. Call `load_processed_duas_from_log()` before starting the executor.

### Outputs

All output files for sheet `<sheet>` go into `{output_base_path}/<sheet>/`:

| File | Content |
|------|---------|
| `MM20YY_Detalles_DUAs__procesados_<sheet>.csv` | Extracted DUA data (25+ fields), `utf-8-sig` encoding |
| `Detalles_DUAs_fallidas_<sheet>.txt` | DUAs that failed after all retries |
| `Detalles_DUAs_procesados_log_<sheet>.txt` | One DUA ID per line — used for resume |
| `data/Datos_Cargados/<sheet>.xlsx` | Local cache of the input sheet |
| `logs/debug.log` | Execution log (no rotation — grows indefinitely) |
| `src/screenshots/` | Error screenshots captured during failed attempts |

## Key Notes

- `src/processors.py` and `config/config.json` are the originals kept for reference — active code is `src/core/`, `src/flows/`, `machine.json`, `session.json`.
- `codigo viejo/` contains archived scripts — do not modify or rely on them.
- Thread count (`cant_hilos`) is kept at `1` to avoid portal rate-limiting. The architecture supports >1 workers transparently.
- Headless mode is faster but hides UI errors; disable it when debugging Selenium interactions.
- The PyInstaller spec (`DetallesBot.spec`) bundles `Names_TicaPortal.xlsx` as a data file. `get_names_path()` in `utils.py` handles both `.exe` and dev-mode path resolution.
