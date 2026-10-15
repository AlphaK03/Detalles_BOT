"""Navegación concurrente con cola durable y reintentos por rondas completas."""
import asyncio
import logging
import os
import sys
import time
import json
from pathlib import Path
from threading import Event
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page

from core.captcha import resolve_captcha
from core.identifiers import dua_fields, validate_result
from core.portal_form import fill_and_submit, wait_form_ready
from core.messages import pending_reason
from core.detail_navigation import install_lightweight_detail


class ExtraStepRequired(RuntimeError):
    """Caso reservado para diagnóstico posterior; no se hace el clic adicional."""


class PlaywrightDUAProcessor:
    def __init__(self, machine_config, output_paths, flow, captcha_lookup, stop_event: Event):
        self.machine = dict(machine_config)
        self.output_paths = output_paths
        self._flow = flow
        self.captcha_lookup = captcha_lookup
        self.stop_event = stop_event
        self.fields = list(flow.extract_data('').columns)
        self._last_export = time.monotonic()
        self._last_notification = 0.0

    def run(self, store, progress_callback):
        for key, default in [('cant_hilos', 1), ('max_retries', 3), ('timeout', 30)]:
            if int(self.machine.get(key, default)) < 1:
                raise ValueError(f'{key} debe ser mayor que cero')
        store.begin_run()
        self._notify(store, progress_callback, force=True)
        try:
            asyncio.run(self._run_async(store, progress_callback))
            summary = store.summary()
            logging.info('%s %d DUAs guardados; %d pendientes.',
                         'Proceso detenido.' if self.stop_event.is_set() else 'Consultas terminadas.',
                         summary['succeeded'], summary['total'] - summary['succeeded'])
        finally:
            # Los resultados se confirmaron antes en SQLite; fallar aquí no los pierde.
            store.export(self.output_paths, self.fields)
            self._notify(store, progress_callback, force=True)

    async def _run_async(self, store, callback):
        summary = store.summary()
        if self.stop_event.is_set() or summary['total'] == summary['succeeded'] + summary['invalid']:
            return
        if getattr(sys, 'frozen', False):
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',
                                  os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright'))
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.machine.get('headless', True))
            try:
                for round_number in range(1, int(self.machine.get('max_retries', 3)) + 1):
                    if self.stop_event.is_set():
                        break
                    logging.info('Consultando los DUAs pendientes.' if round_number == 1 else
                                 'Reintentando automáticamente los DUAs que quedaron pendientes.')
                    await self._run_round(store, browser, round_number, callback)
                    summary = store.summary()
                    if summary['succeeded'] + summary['invalid'] == summary['total']:
                        break
                    if round_number < int(self.machine.get('max_retries', 3)):
                        await self._cooldown(min(2 ** round_number, 30))
            finally:
                await browser.close()

    async def _run_round(self, store, browser, round_number, callback):
        concurrency = int(self.machine.get('cant_hilos', 1))
        if round_number > 1:
            concurrency = min(concurrency, 2)
        workers = [asyncio.create_task(self._worker(store, browser, round_number, callback))
                   for _ in range(concurrency)]
        group = asyncio.gather(*workers)

        async def stopped():
            while not self.stop_event.is_set():
                await asyncio.sleep(0.1)

        watcher = asyncio.create_task(stopped())
        try:
            done, _ = await asyncio.wait([group, watcher], return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                for worker in workers:
                    worker.cancel()
            await group
        except asyncio.CancelledError:
            if not self.stop_event.is_set():
                raise
        finally:
            watcher.cancel()
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.gather(*workers, watcher, return_exceptions=True)

    async def _worker(self, store, browser, round_number, callback):
        context = page = None
        created, uses = 0.0, 0
        reuse = bool(self.machine.get('reuse_context', True))
        try:
            while not self.stop_event.is_set():
                job = store.claim(round_number)
                if job is None:
                    return
                resolved, discard = False, False
                try:
                    try:
                        if context is None:
                            context = await browser.new_context()
                            page = await context.new_page()
                            page.set_default_timeout(int(self.machine.get('timeout', 30)) * 1000)
                            await self._block_static(page)
                            created, uses = time.monotonic(), 0
                        # Cada DUA vuelve al formulario y recibe un CAPTCHA nuevo.
                        # La sesión nunca se comparte con otro trabajador.
                        uses += 1
                        html = await self._fetch_result(page, dua_fields(job['dua']))
                        record = validate_result(self._flow.extract_data(html), job['dua'])
                    except Exception as exc:
                        discard = True
                        evidence = await self._save_evidence(page, job['dua'])
                        kind = 'extra_step' if isinstance(exc, ExtraStepRequired) else type(exc).__name__
                        store.retry(job, exc, kind, evidence)
                        resolved = True
                        last_round = round_number >= int(self.machine.get('max_retries', 3))
                        next_step = 'Queda guardado como pendiente.' if last_round else 'Se reintentará al final.'
                        logging.warning('DUA %s: %s %s', job['dua'], pending_reason(kind, str(exc)), next_step)
                        logging.warning('[%s] Ronda %d: %s: %s', job['dua'], round_number, kind, exc,
                                        extra={'technical_only': True})
                    else:
                        # Los errores de disco siguen siendo fatales y no se reintentan como red.
                        store.complete(job, record)
                        resolved = True
                        logging.info('DUA %s guardado.', job['dua'], extra={'tag': 'SUCCESS'})
                    self._notify(store, callback)
                    if time.monotonic() - self._last_export >= self.machine.get('export_interval', 60):
                        store.export(self.output_paths, self.fields)
                        self._last_export = time.monotonic()
                finally:
                    if not resolved:
                        store.retry(job, 'Intento interrumpido; se retomará al iniciar.',
                                    'interrupted', cancelled=True)
                    if context is not None and (discard or not reuse or uses >= 100 or time.monotonic() - created >= 600):
                        try:
                            await context.close()
                        except Exception:
                            logging.debug('Contexto ya cerrado.', exc_info=True)
                        finally:
                            context = page = None
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    logging.debug('Contexto ya cerrado.', exc_info=True)

    def _notify(self, store, callback, force=False):
        now = time.monotonic()
        if not force and now - self._last_notification < 0.25:
            return
        self._last_notification = now
        callback(store.summary())

    async def _cooldown(self, seconds):
        until = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < until:
            await asyncio.sleep(0.1)

    async def _fetch_result(self, page: Page, row) -> str:
        hook = None
        page._dua_raw_detail = None
        page._dua_form_snapshot = None
        if self.machine.get('lightweight_details', True):
            hook = await install_lightweight_detail(page, self._flow, row['NroDUA'],
                                                    int(self.machine.get('timeout', 30)) * 1000)
        try:
            return await self._fetch_page_result(page, row)
        finally:
            if hook:
                await page.unroute(*hook)

    async def _fetch_page_result(self, page: Page, row) -> str:
        timeout_ms = int(self.machine.get('timeout', 30)) * 1000
        page.set_default_timeout(timeout_ms)
        response = await page.goto(self._flow.start_url, timeout=timeout_ms, wait_until='domcontentloaded')
        if response and response.status >= 400:
            raise RuntimeError(f'Portal respondió HTTP {response.status}')
        extra = page.locator('input[name="SALIR"][value="OK"]')
        if await extra.count():
            raise ExtraStepRequired('Página intermedia: requiere clic adicional')
        await wait_form_ready(page, timeout_ms)
        captcha_text = await self._resolve_captcha(page, timeout_ms)
        try:
            await fill_and_submit(page, row, captcha_text, timeout_ms,
                                  captcha_source=page._dua_captcha_source)
        except Exception:
            if await extra.count():
                raise ExtraStepRequired('El resultado requiere clic adicional') from None
            raise
        if await extra.count():
            raise ExtraStepRequired('El resultado requiere clic adicional')
        return page._dua_raw_detail or await page.content()

    async def _resolve_captcha(self, page, timeout_ms):
        img = await page.wait_for_selector('#captchaImage img', state='attached', timeout=timeout_ms)
        src = await img.get_attribute('src')
        page._dua_captcha_source = src
        return resolve_captcha(urljoin(page.url, src or ''), self.captcha_lookup)

    @staticmethod
    async def _block_static(page):
        async def route_request(route):
            if route.request.resource_type in ('stylesheet', 'font', 'image', 'media'):
                await route.abort()
            else:
                await route.continue_()
        await page.route('**/*', route_request)

    @staticmethod
    def _validate(data, dua_number):
        return validate_result(data, dua_number)

    async def _save_evidence(self, page, dua):
        if page is None or 'diagnostics' not in self.output_paths:
            return ''
        folder = Path(self.output_paths['diagnostics'])
        try:
            folder.mkdir(parents=True, exist_ok=True)
            html = await asyncio.wait_for(page.content(), timeout=3)
            (folder / f'{dua}.html').write_text(html, encoding='utf-8')
            snapshot = getattr(page, '_dua_form_snapshot', None)
            if snapshot:
                (folder / f'{dua}.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
            return str(folder / f'{dua}.html')
        except Exception:
            logging.warning('No se pudo guardar evidencia para %s.', dua, extra={'technical_only': True})
            return ''
