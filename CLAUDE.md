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
- `Names_TicaPortal.xlsx` — CAPTCHA text lookup table (path: `machine.json` → `names_file_path`)

## Architecture

### Entry point
`src/main.py` adds `src/` to `sys.path` and calls `App().mainloop()`.

### GUI (`src/ui/app.py`)
`App(tk.Tk)` — manages the full UI lifecycle:
- Config panel: file selector (populates sheet dropdown on selection), output folder selector
- Progress panel: progress bar + live counters (success / failed / skipped)
- Log panel: `ScrolledText` fed by a custom `logging.Handler`, color-coded by level
- Driver update dialog: detects Edge version, downloads matching driver with progress bar

Processing is launched in a daemon thread that spawns a `ThreadPoolExecutor`. All UI updates from worker threads go through `self.after(0, fn)`.

### Pluggable flow system
The key abstraction for multi-bot reuse:

| File | Role |
|------|------|
| `src/flows/base_flow.py` | `BaseFlow` ABC — defines the 4-method contract every bot implements |
| `src/flows/detalles_flow.py` | `DetallesFlow(BaseFlow)` — navigation and data extraction for this bot |
| `src/core/processor.py` | `DUAProcessor` — generic engine: CAPTCHA, retries, CSV write, duplicate detection |
| `src/core/browser.py` | `create_edge_driver()` — Edge WebDriver factory with request interceptor |

**To create a new bot:** subclass `BaseFlow`, implement `start_url`, `fill_form`, `wait_for_result`, `extract_data`, pass the instance to `DUAProcessor`. Nothing else changes.

### Configuration (two files, clearly separated)

| File | Contains | Changes when |
|------|----------|--------------|
| `config/machine.json` | `base_path`, `output_base_path`, `names_file_path`, `edge_driver_path`, `max_retries`, `timeout`, `cant_hilos` | Changing machine or adjusting processing parameters |
| `config/session.json` | `sheet_name`, `input_file_path`, `progress.{sheet_key}` | UI saves automatically on each run |

Output paths (`output_csv`, `failed_duas`, etc.) are always **computed at runtime** from `output_base_path + sheet_name` — never stored in config.

### Outputs

| File | Content |
|------|---------|
| `Duas_procesados_<sheet>.csv` | Extracted DUA data (25+ fields), `utf-8-sig` encoding |
| `DUAs_fallidas_<sheet>.txt` | DUAs that failed after all retries |
| `data/Datos_Cargados/<sheet>.xlsx` | Local cache of the input sheet |
| `logs/debug.log` | Execution log |

## Key Notes

- `src/processors.py` is the original file kept for reference — the active code is in `src/core/` and `src/flows/`.
- `config/config.json` is the original config kept for reference — the active config is `machine.json` + `session.json`.
- `src/driver_updater.py` is used by the driver dialog in `app.py` to auto-update `msedgedriver.exe`.
- Thread count (`cant_hilos`) is kept at `1` to avoid portal rate-limiting. The architecture supports >1 workers transparently.
- CAPTCHA resolution is image-URL lookup against `Names_TicaPortal.xlsx` — no OCR involved.
- `load_processed_duas_from_csv()` must be called before starting the executor to prevent duplicate writes on resume.
- `codigo viejo/` contains archived scripts — do not modify or rely on them.
