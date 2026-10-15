import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core.detail_navigation import install_lightweight_detail
from core.job_store import JobStore
from flows.detalles_flow import DetallesFlow
from test_queue import FakeBrowser, FakeContext, FakeProcessor, html
from utils import compute_output_paths

DUA = '001-2026-020591'


class LightweightTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self, raw, dua=DUA, flow=None):
        response = SimpleNamespace(status=200, text=AsyncMock(return_value=raw), dispose=AsyncMock())
        route = SimpleNamespace(request=SimpleNamespace(method='GET', is_navigation_request=lambda: True),
                                fetch=AsyncMock(return_value=response), fulfill=AsyncMock(), fallback=AsyncMock())
        page = SimpleNamespace(route=AsyncMock())
        _, handler = await install_lightweight_detail(page, flow or DetallesFlow(), dua, 1000)
        await handler(route)
        response.dispose.assert_awaited_once()
        return page, route

    async def test_removes_scripts_preserving_all_values_and_empty_error_is_allowed(self):
        raw = html(DUA) + '<span id="ERROR"></span><script>throw Error("heavy");</script><img src="large.png">'
        page, route = await self.capture(raw)
        lean = route.fulfill.call_args.kwargs['body']
        self.assertNotIn('<script', lean)
        self.assertNotIn('<img', lean)
        self.assertEqual(DetallesFlow().extract_data(raw).to_dict('records'),
                         DetallesFlow().extract_data(lean).to_dict('records'))
        self.assertEqual(page._dua_raw_detail, raw)

    async def test_wrong_identity_keeps_original_navigation(self):
        page, route = await self.capture(html('001-2026-999999'))
        self.assertNotIn('body', route.fulfill.call_args.kwargs)
        self.assertFalse(hasattr(page, '_dua_raw_detail'))

    async def test_warning_and_extra_step_are_not_simplified(self):
        for extra in ('<span id="ERROR">Advertencia</span>', '<input name="SALIR" value="OK">'):
            with self.subTest(extra=extra):
                _, route = await self.capture(html(DUA) + extra)
                self.assertNotIn('body', route.fulfill.call_args.kwargs)

    async def test_value_difference_falls_back_to_original(self):
        class DifferentAfterRemoval(DetallesFlow):
            def extract_data(self, raw):
                data = super().extract_data(raw)
                if '<script' not in raw:
                    data['estado'] = 'changed'
                return data
        _, route = await self.capture(html(DUA) + '<script>data</script>', flow=DifferentAfterRemoval())
        self.assertNotIn('body', route.fulfill.call_args.kwargs)

    async def test_response_is_disposed_when_fulfill_fails(self):
        response = SimpleNamespace(status=200, text=AsyncMock(return_value=html(DUA)), dispose=AsyncMock())
        route = SimpleNamespace(request=SimpleNamespace(method='GET', is_navigation_request=lambda: True),
                                fetch=AsyncMock(return_value=response), fulfill=AsyncMock(side_effect=RuntimeError('closed')))
        page = SimpleNamespace(route=AsyncMock())
        _, handler = await install_lightweight_detail(page, DetallesFlow(), DUA, 1000)
        with self.assertRaises(RuntimeError):
            await handler(route)
        response.dispose.assert_awaited_once()


class CountingBrowser(FakeBrowser):
    def __init__(self):
        self.created = self.closed = 0

    async def new_context(self):
        self.created += 1
        browser = self
        class Context(FakeContext):
            async def close(self):
                browser.closed += 1
        return Context()


class WorkerReuseTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, reuse=True, failed=False, count=4):
        with tempfile.TemporaryDirectory() as folder:
            store = JobStore(Path(folder) / 'jobs.sqlite3')
            try:
                duas = [f'001-2026-{i:06d}' for i in range(1, count + 1)]
                store.import_values(duas); store.begin_run()
                processor = FakeProcessor(compute_output_paths(folder, 'reuse'), Event())
                processor.machine.update(cant_hilos=1, reuse_context=reuse, max_retries=1, export_interval=3600)
                processor._save_evidence = AsyncMock(return_value='')
                if failed:
                    processor.fail.add(duas[0])
                browser = CountingBrowser()
                await processor._run_round(store, browser, 1, lambda summary: None)
                self.assertEqual(browser.closed, browser.created)
                self.assertEqual(store.summary()['running'], 0)
                self.assertEqual(store.summary()['succeeded'], count - int(failed))
                return browser.created
            finally:
                store.close()

    async def test_worker_reuses_one_context_for_successful_jobs(self):
        self.assertEqual(await self.scenario(), 1)

    async def test_reuse_can_be_disabled(self):
        self.assertEqual(await self.scenario(reuse=False), 4)

    async def test_failed_query_discards_session_before_next_job(self):
        self.assertEqual(await self.scenario(failed=True), 2)

    async def test_session_renews_after_100_jobs(self):
        self.assertEqual(await self.scenario(count=102), 2)
