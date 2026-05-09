"""playwright_processor.py — Motor Playwright de procesamiento de DUAs.

Un solo proceso Chromium compartido con N contextos aislados concurrentes:
  - Playwright carga el form y ejecuta JS → GeneXus rellena div#captchaImage
  - Lookup en names_df por URL de imagen (sin descargar nada)
  - Click DETALLE → redirect a hcimdpola.aspx → wait_for_selector span_CODI_ADUAN
  - extract_data() de DetallesFlow reutilizado sin cambios

Comparado con Selenium:
  - 1 proceso Chromium vs N procesos Edge
  - ~30 MB por contexto vs ~300 MB por instancia Edge
"""
import os
import asyncio
import logging
from threading import Event
from typing import Callable
from urllib.parse import urljoin

import pandas as pd
from playwright.async_api import async_playwright, Browser, Page

from flows.base_flow import BaseFlow

_PORTAL_BASE = 'https://portaltica.hacienda.go.cr'

_PROCESSED_DUAS: set = set()


def load_processed_duas_from_log(log_path: str) -> None:
    """Pre-carga DUAs ya procesados. Llamar antes de iniciar el procesamiento."""
    if not os.path.exists(log_path):
        return
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                dua = line.strip()
                if dua:
                    _PROCESSED_DUAS.add(dua)
        logging.info("Cargados %d DUAs previos desde %s.", len(_PROCESSED_DUAS), log_path)
    except Exception as e:
        logging.error("No se pudo cargar DUAs previos: %s", e)


class PlaywrightDUAProcessor:
    """
    Procesa DUAs usando un browser Chromium compartido con contextos aislados.
    Diseñado para ser llamado desde un hilo worker (app._run).
    """

    def __init__(
        self,
        machine_config: dict,
        output_paths: dict,
        flow: BaseFlow,
        names_df: pd.DataFrame,
        stop_event: Event,
    ):
        self.machine = machine_config
        self.output_paths = output_paths
        self._flow = flow
        self.names_df = names_df
        self.stop_event = stop_event

    # ── API pública ──────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame, start_from: int, progress_callback: Callable) -> None:
        """Entry point sincrónico — lanzado desde el hilo daemon de app._run()."""
        asyncio.run(self._run_async(df, start_from, progress_callback))

    # ── Motor async ──────────────────────────────────────────────────────────

    async def _run_async(
        self, df: pd.DataFrame, start_from: int, progress_callback: Callable
    ) -> None:
        n_workers = self.machine.get('cant_hilos', 1)
        headless = self.machine.get('headless', True)
        io_lock  = asyncio.Lock()
        dup_lock = asyncio.Lock()

        # Cola con los índices pendientes (memory-efficient para 70K+ filas)
        queue: asyncio.Queue = asyncio.Queue()
        skipped = 0
        for idx, row in df.iterrows():
            if idx <= start_from:
                skipped += 1
                continue
            if skipped > 0:
                logging.info("Saltadas %d filas ya procesadas (0–%d).", skipped, start_from)
                skipped = 0
            await queue.put((int(idx), row))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            logging.info("Browser Chromium iniciado (headless=%s, workers=%d).", headless, n_workers)

            workers = [
                self._worker(queue, browser, io_lock, dup_lock, progress_callback)
                for _ in range(n_workers)
            ]
            await asyncio.gather(*workers)
            await browser.close()

    async def _worker(
        self, queue: asyncio.Queue, browser: Browser,
        io_lock: asyncio.Lock, dup_lock: asyncio.Lock,
        progress_callback: Callable,
    ) -> None:
        while not self.stop_event.is_set():
            try:
                idx, row = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._process_dua(browser, io_lock, dup_lock, idx, row, progress_callback)
            queue.task_done()

    async def _process_dua(
        self, browser: Browser,
        io_lock: asyncio.Lock, dup_lock: asyncio.Lock,
        idx: int, row, progress_callback: Callable,
    ) -> None:
        dua_number = row['NroDUA']
        max_retries = self.machine['max_retries']

        for attempt in range(1, max_retries + 1):
            if self.stop_event.is_set():
                return
            context = await browser.new_context()
            try:
                page = await context.new_page()
                await self._block_static(page)

                html = await self._fetch_result(page, row)
                data = self._flow.extract_data(html)
                self._validate(data, dua_number)

                extracted_dua = data.iloc[0]['numero_del_dua'].strip()

                async with dup_lock:
                    if extracted_dua in _PROCESSED_DUAS:
                        logging.warning("DUA %s ya procesado. Omitido.", extracted_dua)
                        progress_callback(idx, 'skipped')
                        return
                    _PROCESSED_DUAS.add(extracted_dua)

                async with io_lock:
                    self._write_csv(data)
                    self._log_processed(extracted_dua)

                logging.info("DUA %s guardado.", extracted_dua, extra={'tag': 'SUCCESS'})
                progress_callback(idx, 'success')
                return

            except Exception as e:
                logging.warning("[%s] Intento %d/%d: %s: %s",
                                dua_number, attempt, max_retries, type(e).__name__, e)
            finally:
                await context.close()

        logging.error("[%s] Reintentos agotados.", dua_number)
        self._log_failed(dua_number)
        progress_callback(idx, 'failed')

    async def _fetch_result(self, page: Page, row) -> str:
        timeout_ms = self.machine['timeout'] * 1000
        start_url  = f'{_PORTAL_BASE}/TicaExterno/hcimppon.aspx'

        await page.goto(start_url, timeout=timeout_ms)

        # Descartar página de rectificación si el portal la muestra
        salir = page.locator('input[name="SALIR"][value="OK"]')
        if await salir.count() > 0:
            logging.info("Página de rectificación detectada. Descartando...")
            await salir.click()
            await page.wait_for_load_state('networkidle', timeout=timeout_ms)

        captcha_text = await self._resolve_captcha(page, timeout_ms)

        await page.fill('#vVCODI_ADUA', str(row['Aduana']))
        await page.fill('#vVANO_PRE',   str(row['Año']))
        await page.fill('#vVNUME_CORR', str(row['Número']))
        await page.fill('#_cfield',     captcha_text)

        await page.click('[name="DETALLE"]')
        await page.wait_for_selector('#span_CODI_ADUAN', timeout=timeout_ms)

        return await page.content()

    async def _resolve_captcha(self, page: Page, timeout_ms: int) -> str:
        # Esperar a que GeneXus JS inyecte la imagen en div#captchaImage
        img = await page.wait_for_selector('#captchaImage img', timeout=timeout_ms)
        src = await img.get_attribute('src')
        url = urljoin(_PORTAL_BASE, src or '')
        matches = self.names_df.loc[self.names_df['Path'] == url, 'Word'].values
        if len(matches) == 0:
            raise ValueError(f"CAPTCHA no encontrado en lookup: {url}")
        return str(matches[0])

    @staticmethod
    async def _block_static(page: Page) -> None:
        """Bloquea CSS y fuentes para acelerar la carga (JS e imágenes se mantienen)."""
        await page.route(
            '**/*.{css,woff,woff2,ttf,eot}',
            lambda route: route.abort(),
        )

    # ── IO sincrónico (llamado dentro de io_lock) ────────────────────────────

    def _validate(self, data: pd.DataFrame, dua_number: str) -> None:
        if (data is None or data.empty
                or 'numero_del_dua' not in data.columns
                or data['numero_del_dua'].iloc[0].strip() == ''):
            raise ValueError(f"Datos vacíos para DUA {dua_number}")

    def _write_csv(self, data: pd.DataFrame) -> None:
        path = self.output_paths['output_csv']
        header = not os.path.exists(path)
        data.to_csv(path, mode='a', header=header, index=False, encoding='utf-8-sig')

    def _log_processed(self, dua_number: str) -> None:
        with open(self.output_paths['processed_log'], 'a', encoding='utf-8') as f:
            f.write(f"{dua_number}\n")

    def _log_failed(self, dua_number: str) -> None:
        with open(self.output_paths['failed_duas'], 'a', encoding='utf-8') as f:
            f.write(f"{dua_number}\n")
