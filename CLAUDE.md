# Repository guidance — Detalles BOT

The active branch architecture is documented in [README.md](README.md) and
[docs/analisis_astracode.md](docs/analisis_astracode.md). Read those before relying
on older migration notes.

For cross-bot replication and session handoff, read
[docs/GUIA_REPLICACION_BOTS.md](docs/GUIA_REPLICACION_BOTS.md). It records the
implemented HTTP/browser strategies, invariants, configuration, evidence and
limits. Keep its identical copy in Manifiestos_Bot2 synchronized when updating it.

- Entry point: `python src/main.py` (Tk GUI).
- Active engine: `src/core/playwright_processor.py`; Chromium with isolated contexts.
- Contexts are isolated per worker and reused sequentially, reset on error or
  after 100 jobs / 10 minutes. `core/detail_navigation.py` simplifies only validated
  detail documents with identical extracted values; form JavaScript stays active.
- The submission guard covers both navigation and AJAX POSTs; preserve that check
  and the CAPTCHA-source check when changing the browser strategy.
- Durable state: `src/core/job_store.py`; local SQLite databases under `data/queues/`.
- CAPTCHA catalog: `config/captcha_lookup.json`, loaded once by `core/captcha.py`.
  The active app and spec do not read `Names_TicaPortal.xlsx`.
- The Excel boundary is `JobStore.import_excel`; workers use normalized DUA strings.
- GUI imports use append mode through `TableCatalog`: a confirmed existing name
  adds only new DUAs to that table. Never overwrite its results, retries or invalid
  entries when importing a second quincena. Check retained results as well as jobs.
- SQLite enforces unique non-null DUAs per table. Import reports and source history
  commit with the imported rows; a failed append must roll back the entire load.
- Results and success status commit in the same transaction. CSV/JSON are exports.
- Never restore processing from the highest completed row index or a processed TXT.
- Keep failed/interrupted work retryable. A batch is complete only when every
  active job has a committed result. Do not automate the extra-click cases yet.
- GUI workers communicate via a queue; Tk widgets are updated on the main thread.
- Hold `RunLock(database)` before importing, recovering, processing or exporting
  a batch. Do not reset running jobs belonging to another active instance.
- Default portal concurrency is one. Tests must be offline unless a live probe is
  explicitly intended; `scripts/probe_portal.py` accepts at most four identifiers.
- Run checks: `python -m unittest discover -s tests -v`.
- Package via `DetallesBot.spec`; it includes the JSON catalog. Chromium is external.

`src/core/http_processor.py`, `src/core/processor.py`, `src/processors.py`,
`src/core/browser.py`, `src/driver_updater.py` and `config/config.json` are legacy,
not the active GUI path. `codigo viejo/` is archived; do not modify it.
Keep input files, SQLite databases, screenshots and portal HTML out of Git.
